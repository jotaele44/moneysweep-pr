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



def test_runtime_files_must_match_exact_producer_commit(tmp_path: Path, monkeypatch):
    clean = tmp_path / "runtime.py"
    clean.write_bytes(b"committed\n")
    monkeypatch.setattr(finalizer, "ROOT", tmp_path)
    monkeypatch.setattr(finalizer, "_git_blob", lambda commit, relative: b"committed\n")

    finalizer._assert_paths_bound_to_commit([clean], "a" * 40)

    clean.write_bytes(b"dirty\n")
    with pytest.raises(SystemExit, match="dirty:runtime.py"):
        finalizer._assert_paths_bound_to_commit([clean], "a" * 40)


def test_runtime_binding_rejects_unresolvable_or_missing_paths(tmp_path: Path, monkeypatch):
    clean = tmp_path / "runtime.py"
    clean.write_bytes(b"committed\n")
    missing = tmp_path / "missing.py"
    monkeypatch.setattr(finalizer, "ROOT", tmp_path)

    def fail_blob(commit, relative):
        raise SystemExit("unresolvable")

    monkeypatch.setattr(finalizer, "_git_blob", fail_blob)
    with pytest.raises(SystemExit, match=r"unbound:runtime\.py.*missing:missing\.py"):
        finalizer._assert_paths_bound_to_commit([clean, missing], "b" * 40)



def test_thehub_replay_receipt_binds_both_commits_and_exact_hashes(tmp_path: Path):
    package = tmp_path / "package.json"
    producer_receipt = tmp_path / "receipt.json"
    release = tmp_path / "release.json"
    scope = tmp_path / "scope.json"
    package.write_bytes(b"package\n")
    producer_receipt.write_bytes(b"receipt\n")
    release.write_bytes(b"release\n")
    scope.write_bytes(b"scope\n")

    result = finalizer._thehub_replay_receipt(
        producer_commit="a" * 40,
        consumer_commit="b" * 40,
        package_path=package,
        receipt_path=producer_receipt,
        release_path=release,
        scope_path=scope,
    )
    assert result["state"] == "PASS"
    assert result["producerCommit"] == "a" * 40
    assert result["consumerCommit"] == "b" * 40
    assert result["githubActionsExecution"] == "WAIVED_BY_USER"
    assert result["assertsGithubActionsPass"] is False
    assert len(result["replayReceiptSha256"]) == 64


def test_thehub_checkout_binding_rejects_dirty_consumer_bytes(tmp_path: Path, monkeypatch):
    relative = Path("server/backend/moneysweep_leaderboards.py")
    path = tmp_path / relative
    path.parent.mkdir(parents=True)
    path.write_bytes(b"clean\n")

    monkeypatch.setattr(finalizer, "THEHUB_RUNTIME_RELATIVE_PATHS", [relative])
    monkeypatch.setattr(finalizer, "_repo_git_head", lambda root: "c" * 40)
    monkeypatch.setattr(finalizer, "_repo_git_blob", lambda root, commit, rel: b"clean\n")
    assert finalizer._assert_thehub_checkout_bound_to_head(tmp_path) == "c" * 40

    path.write_bytes(b"dirty\n")
    with pytest.raises(SystemExit, match="dirty:server/backend/moneysweep_leaderboards.py"):
        finalizer._assert_thehub_checkout_bound_to_head(tmp_path)
