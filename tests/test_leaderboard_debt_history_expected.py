from __future__ import annotations

import pytest

from server.backend.leaderboard_history import compare, make_snapshot


BASELINE = [
    ("entity_5204a3d8f84bbfcd", "COFINA", 16314000000.0, 1),
    ("entity_125b538f289a4708", "Commonwealth", 11800000000.0, 2),
    ("entity_b182f85acf46f69b", "HTA", 4108400000.0, 3),
    ("entity_6c1d858c1babe390", "PREPA", 1193000000.0, 4),
    ("entity_c5fb8a7f44e8ff18", "PRASA", 1150000000.0, 5),
]

CURRENT = [
    ("entity_5204a3d8f84bbfcd", "COFINA", 16314000000.0, 1),
    ("entity_125b538f289a4708", "Commonwealth", 11800000000.0, 2),
    ("entity_b182f85acf46f69b", "HTA", 4108400000.0, 3),
    ("entity_b14376987d82d5ee", "PRPFC", 1255000000.0, 4),
    ("entity_6c1d858c1babe390", "PREPA", 1193000000.0, 5),
    ("entity_c5fb8a7f44e8ff18", "PRASA", 1150000000.0, 6),
    ("entity_d363e4ddf2ce6a5d", "GDB", 900000000.0, 7),
    ("entity_7cf79ff780fb8279", "PRIFA", 500000000.0, 8),
    ("entity_2c16f9ae54df7e1e", "CCDA", 469900000.0, 9),
    ("entity_cc41784f4b40b6ff", "UPR", 359000000.0, 10),
    ("entity_5f99300da364ea64", "PRIDCO", 240000000.0, 11),
    ("entity_efcec09764306ade", "Ports", 220000000.0, 12),
    ("entity_c6aa8887d7248228", "PRHFA", 180000000.0, 13),
    ("entity_e73c9879d715653a", "MFA", 155000000.0, 14),
]


def _ranking(rows, source_hash):
    return {
        "categoryId": "debt_issuance",
        "metricType": "DEBT_ISSUED_PAR",
        "rankingVersion": "moneysweep.leaderboard/v1.1",
        "certificationState": "PROVISIONAL",
        "topN": None,
        "candidateCount": len(rows),
        "filters": {"startYear": None, "endYear": None, "municipality": None, "entityType": None, "currency": "USD"},
        "currencies": ["USD"],
        "accounting": {
            "inputRecords": 11 if len(rows) == 5 else 20,
            "outOfScopeRecords": 0,
            "retainedRecords": 11 if len(rows) == 5 else 20,
            "excludedRecords": 0,
            "unresolvedRecords": 0,
            "inScopeRecords": 11 if len(rows) == 5 else 20,
            "arithmeticClosed": True,
        },
        "rows": [
            {
                "entityId": entity_id,
                "canonicalEntityId": entity_id,
                "entityDisplayName": name,
                "entityType": "agency",
                "metricType": "DEBT_ISSUED_PAR",
                "metricValue": value,
                "currency": "USD",
                "recordCount": 1,
                "entityResolutionState": "CANONICAL_V1_ENTITY_ID",
                "financialValueState": "MEASURED_PAR_AMOUNT",
                "rank": rank,
            }
            for entity_id, name, value, rank in rows
        ],
        "sourceManifestations": [
            {"path": "data/canonical_v1/debt_instruments.csv", "sha256": source_hash},
        ],
        "methodology": {"identity": "canonical_v1 issuer_entity_id only"},
    }


def _runtime():
    return {
        "state": "FROZEN",
        "producerCommit": "a" * 40,
        "files": [{"path": "leaderboard_adapters.py", "sha256": "f" * 64}],
    }


@pytest.mark.unit
def test_known_debt_source_expansion_has_expected_dataset_delta():
    prior = make_snapshot(
        _ranking(BASELINE, "1" * 64),
        captured_at="2026-06-01T12:40:24+00:00",
        snapshot_id="debt-baseline",
        runtime_manifest=_runtime(),
    )
    current = make_snapshot(
        _ranking(CURRENT, "2" * 64),
        captured_at="2026-09-03T16:35:24+00:00",
        snapshot_id="debt-current",
        runtime_manifest=_runtime(),
    )
    result = compare(prior, current, limit=25)
    assert result["movementState"] == "COMPARABLE_SNAPSHOT_DELTA"
    assert result["sourceManifestationChanged"] is True
    assert result["runtimeManifestationChanged"] is False
    assert result["economicChangeInferenceAllowed"] is False
    assert result["movementCounts"] == {
        "NEW": 9,
        "EXITED": 0,
        "UP": 0,
        "DOWN": 2,
        "UNCHANGED": 3,
    }
    by_id = {row["entityId"]: row for row in result["rows"]}
    assert by_id["entity_6c1d858c1babe390"]["movementState"] == "DOWN"
    assert by_id["entity_6c1d858c1babe390"]["valueDelta"] == 0
    assert by_id["entity_c5fb8a7f44e8ff18"]["movementState"] == "DOWN"
    assert by_id["entity_c5fb8a7f44e8ff18"]["valueDelta"] == 0
    assert by_id["entity_b14376987d82d5ee"]["movementState"] == "NEW"
