from __future__ import annotations

from pathlib import Path

import pytest

from scripts import finalize_leaderboard_release as finalizer


def _movement(**overrides):
    value = {
        "movementState": "COMPARABLE_SNAPSHOT_DELTA",
        "sourceManifestationChanged": True,
        "runtimeManifestationChanged": False,
        "economicChangeInferenceAllowed": False,
        "movementCounts": {
            "NEW": 9,
            "EXITED": 0,
            "UP": 0,
            "DOWN": 2,
            "UNCHANGED": 3,
        },
        "rows": [
            {"entityId": "existing", "movementState": "DOWN", "valueDelta": 0.0},
            {"entityId": "new", "movementState": "NEW", "valueDelta": 100.0},
        ],
    }
    value.update(overrides)
    return value


def _expected():
    return {
        "NEW": 9,
        "EXITED": 0,
        "UP": 0,
        "DOWN": 2,
        "UNCHANGED": 3,
        "existingEntityValueChanges": 0,
    }


def test_expected_history_delta_passes_only_with_source_change_and_same_runtime():
    finalizer._verify_expected_delta(_movement(), _expected())


@pytest.mark.parametrize(
    "override",
    [
        {"sourceManifestationChanged": False},
        {"runtimeManifestationChanged": True},
        {"economicChangeInferenceAllowed": True},
        {"movementCounts": {"NEW": 8, "EXITED": 0, "UP": 0, "DOWN": 2, "UNCHANGED": 3}},
    ],
)
def test_expected_history_delta_fails_closed_on_semantic_drift(override):
    with pytest.raises(SystemExit):
        finalizer._verify_expected_delta(_movement(**override), _expected())


def test_immutable_write_is_idempotent_but_rejects_different_bytes(tmp_path: Path):
    path = tmp_path / "snapshot.json"
    finalizer._write_immutable(path, b"one\n")
    finalizer._write_immutable(path, b"one\n")
    with pytest.raises(SystemExit, match="refusing to overwrite immutable artifact"):
        finalizer._write_immutable(path, b"two\n")


def test_producer_documents_keep_actions_waiver_and_gate_promotion():
    release = {
        "certification_state": "BLOCKED",
        "certification_issued": False,
        "promotion_authorized": False,
        "non_blocking_waivers": [
            {"id": "GITHUB_ACTIONS_EXECUTION", "state": "WAIVED_BY_USER", "asserts_pass": False}
        ],
    }
    receipt = {
        "state": "BLOCKED",
        "certificationIssued": False,
        "promotionAuthorized": False,
        "nonBlockingWaivers": [
            {"id": "GITHUB_ACTIONS_EXECUTION", "state": "WAIVED_BY_USER", "assertsPass": False}
        ],
    }
    snapshot = {"snapshotSha256": "a" * 64}
    history = {"receiptSha256": "b" * 64}

    producer_release, producer_receipt = finalizer._producer_documents(
        release_template=release,
        receipt_template=receipt,
        runtime_commit="c" * 40,
        certified_snapshot=snapshot,
        history_receipt=history,
        scope_hash="d" * 64,
        promote=False,
    )
    assert producer_release["certification_state"] == "PASS"
    assert producer_release["promotion_authorized"] is False
    assert producer_release["non_blocking_waivers"][0]["asserts_pass"] is False
    assert producer_receipt["state"] == "PASS"
    assert producer_receipt["zeroMaterialUnresolvedResidue"] is True
    assert producer_receipt["promotionAuthorized"] is False
    assert producer_receipt["certificationPhraseAuthorized"] is False
    assert producer_receipt["nonBlockingWaivers"][0]["assertsPass"] is False

    promoted_release, promoted_receipt = finalizer._producer_documents(
        release_template=producer_release,
        receipt_template=producer_receipt,
        runtime_commit="c" * 40,
        certified_snapshot=snapshot,
        history_receipt=history,
        scope_hash="d" * 64,
        promote=True,
    )
    assert promoted_release["promotion_authorized"] is True
    assert promoted_release["blockers"] == []
    assert promoted_receipt["promotionAuthorized"] is True
    assert promoted_receipt["certificationPhraseAuthorized"] is True
    assert promoted_receipt["blockingResidue"] == []
