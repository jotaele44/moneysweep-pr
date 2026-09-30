from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_DIR = ROOT / "data" / "manifests" / "leaderboards" / "independent_replay"
HISTORY = EVIDENCE_DIR / "debt_history_independent_replay_v1.json"
BASELINE = EVIDENCE_DIR / "debt_baseline_v1.json"
CURRENT = EVIDENCE_DIR / "debt_current_v1.json"

EXPECTED_RECEIPT_SHA256 = "a520cb9e3b8bf894635954380ccee6ab03e2cc09e6833cf6e60553d10677fda3"
EXPECTED_COUNTS = {"NEW": 9, "EXITED": 0, "UP": 0, "DOWN": 2, "UNCHANGED": 3}


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _canonical_sha256(value: dict, *, omit: str | None = None) -> str:
    payload = dict(value)
    if omit:
        payload.pop(omit, None)
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def test_independent_debt_history_replay_is_frozen_and_bounded():
    history = _load(HISTORY)
    baseline = _load(BASELINE)
    current = _load(CURRENT)

    assert history["schemaVersion"] == "moneysweep.leaderboard-independent-history-replay/v1"
    assert history["verifierState"] == "PASS"
    assert history["applicationRuntimeCertification"] == "NOT_ASSERTED"
    assert history["expectedDeltaMatched"] is True
    assert history["movementCounts"] == EXPECTED_COUNTS
    assert history["existingEntityValueChanges"] == 0
    assert history["sourceManifestationChanged"] is True
    assert history["runtimeManifestationChanged"] is False
    assert history["economicChangeInferenceAllowed"] is False

    receipt = dict(history)
    receipt.pop("receiptSha256")
    assert hashlib.sha256(
        json.dumps(receipt, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest() == EXPECTED_RECEIPT_SHA256
    assert history["receiptSha256"] == EXPECTED_RECEIPT_SHA256

    for snapshot, expected_rows, expected_input in ((baseline, 5, 11), (current, 14, 20)):
        assert snapshot["snapshotMode"] == "HISTORICAL_GIT_SOURCE_REPLAY_INDEPENDENT_VERIFIER"
        assert snapshot["runtimeManifest"]["state"] == "INDEPENDENT_REPLAY"
        verification = snapshot["runtimeManifest"]["verification"]
        assert verification["pythonRuntimeExecuted"] is False
        assert verification["assertsApplicationRuntimePass"] is False
        assert verification["githubActionsExecution"] == "WAIVED_BY_USER"
        assert snapshot["accounting"]["arithmeticClosed"] is True
        assert snapshot["accounting"]["inputRecords"] == expected_input
        assert snapshot["accounting"]["excludedRecords"] == 0
        assert snapshot["accounting"]["unresolvedRecords"] == 0
        assert snapshot["candidateCount"] == expected_rows
        assert len(snapshot["rows"]) == expected_rows
        assert snapshot["snapshotSha256"] == _canonical_sha256(snapshot, omit="snapshotSha256")


def test_independent_replay_does_not_occupy_canonical_snapshot_namespace():
    canonical = ROOT / "data" / "manifests" / "leaderboards" / "snapshots"
    evidence_paths = {BASELINE.resolve(), CURRENT.resolve()}
    assert all(path.parent == EVIDENCE_DIR.resolve() for path in evidence_paths)
    if canonical.exists():
        assert not evidence_paths.intersection({path.resolve() for path in canonical.glob("*.json")})
