from __future__ import annotations

from copy import deepcopy

import pytest

from server.backend.leaderboard_history import compare, make_snapshot, verify_snapshot


def _ranking(*, value_a=100.0, value_b=50.0, source_hash="a" * 64):
    return {
        "categoryId": "contract_award",
        "metricType": "AWARDED",
        "rankingVersion": "moneysweep.leaderboard/v1.1",
        "certificationState": "PROVISIONAL",
        "topN": None,
        "candidateCount": 2,
        "filters": {"currency": "USD", "startYear": None, "endYear": None},
        "currencies": ["USD"],
        "accounting": {
            "inputRecords": 2,
            "outOfScopeRecords": 0,
            "retainedRecords": 2,
            "excludedRecords": 0,
            "unresolvedRecords": 0,
            "inScopeRecords": 2,
            "arithmeticClosed": True,
        },
        "rows": [
            {"entityId": "entity_a", "entityDisplayName": "A", "metricValue": value_a, "rank": 1, "currency": "USD"},
            {"entityId": "entity_b", "entityDisplayName": "B", "metricValue": value_b, "rank": 2, "currency": "USD"},
        ],
        "sourceManifestations": [{"path": "data.csv", "sha256": source_hash}],
        "methodology": {"identity": "stable id"},
    }


@pytest.mark.unit
def test_snapshot_hash_detects_tampering():
    snapshot = make_snapshot(_ranking(), captured_at="2026-09-01T00:00:00+00:00", snapshot_id="s1")
    assert verify_snapshot(snapshot) == []
    tampered = deepcopy(snapshot)
    tampered["rows"][0]["metricValue"] = 999
    assert "snapshot_sha256" in verify_snapshot(tampered)


@pytest.mark.unit
def test_snapshot_requires_complete_candidate_universe_and_closed_arithmetic():
    ranking = _ranking()
    ranking["topN"] = 25
    with pytest.raises(ValueError, match="complete candidate universe"):
        make_snapshot(ranking, captured_at="2026-09-01T00:00:00+00:00", snapshot_id="s1")
    ranking = _ranking()
    ranking["accounting"]["arithmeticClosed"] = False
    with pytest.raises(ValueError, match="accounting"):
        make_snapshot(ranking, captured_at="2026-09-01T00:00:00+00:00", snapshot_id="s1")


@pytest.mark.unit
def test_noncomparable_filters_fail_closed():
    prior = make_snapshot(_ranking(), captured_at="2026-09-01T00:00:00+00:00", snapshot_id="s1")
    changed = _ranking()
    changed["filters"] = {"currency": "USD", "startYear": 2025, "endYear": None}
    current = make_snapshot(changed, captured_at="2026-09-08T00:00:00+00:00", snapshot_id="s2")
    result = compare(prior, current)
    assert result["movementState"] == "UNRESOLVED_NONCOMPARABLE_SNAPSHOTS"
    assert result["rows"] == []


@pytest.mark.unit
def test_source_hash_change_blocks_economic_change_inference():
    prior = make_snapshot(_ranking(value_a=100, value_b=50), captured_at="2026-09-01T00:00:00+00:00", snapshot_id="s1")
    current = make_snapshot(_ranking(value_a=120, value_b=50, source_hash="b" * 64), captured_at="2026-09-08T00:00:00+00:00", snapshot_id="s2")
    result = compare(prior, current)
    assert result["sourceManifestationChanged"] is True
    assert result["economicChangeInferenceAllowed"] is False
    assert any(row["entityId"] == "entity_a" for row in result["rows"])


@pytest.mark.unit
def test_duplicate_entity_ids_in_snapshot_are_invalid():
    snapshot = make_snapshot(_ranking(), captured_at="2026-09-01T00:00:00+00:00", snapshot_id="s1")
    duplicate = deepcopy(snapshot)
    duplicate["rows"][1]["entityId"] = "entity_a"
    duplicate.pop("snapshotSha256")
    from server.backend.leaderboard_history import snapshot_sha256
    duplicate["snapshotSha256"] = snapshot_sha256(duplicate)
    assert "duplicate_entity_id" in verify_snapshot(duplicate)
