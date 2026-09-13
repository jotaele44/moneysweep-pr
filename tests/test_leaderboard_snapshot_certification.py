from __future__ import annotations

from copy import deepcopy

import pytest

from scripts.certify_leaderboard_snapshot import certification_errors, certify
from server.backend.leaderboard_history import make_snapshot


def _scope():
    return {
        "schemaVersion": "moneysweep.leaderboard-certification-scope/v1",
        "scopeId": "moneysweep.leaderboard.production-v1",
        "rankingContractVersion": "moneysweep.leaderboard/v1.1",
        "ciExecutionPolicy": {"state": "WAIVED_BY_USER", "blocking": False, "assertsPass": False},
        "includedCategories": [
            {
                "categoryId": "debt_issuance",
                "metricType": "DEBT_ISSUED_PAR",
                "identityNamespace": "CANONICAL_V1_ENTITY_ID",
                "currencyUniverse": ["USD"],
                "requiredAccounting": {
                    "arithmeticClosed": True,
                    "unresolvedRecords": 0,
                    "excludedRecords": 0,
                },
            }
        ],
    }


def _ranking():
    return {
        "categoryId": "debt_issuance",
        "metricType": "DEBT_ISSUED_PAR",
        "rankingVersion": "moneysweep.leaderboard/v1.1",
        "certificationState": "PROVISIONAL",
        "topN": None,
        "candidateCount": 2,
        "filters": {"currency": "USD"},
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
            {
                "entityId": "e1",
                "canonicalEntityId": "e1",
                "entityDisplayName": "Issuer One",
                "entityType": "agency",
                "metricType": "DEBT_ISSUED_PAR",
                "metricValue": 150.0,
                "currency": "USD",
                "recordCount": 2,
                "entityResolutionState": "CANONICAL_V1_ENTITY_ID",
                "financialValueState": "MEASURED_PAR_AMOUNT",
                "rank": 1,
            },
            {
                "entityId": "e2",
                "canonicalEntityId": "e2",
                "entityDisplayName": "Issuer Two",
                "entityType": "agency",
                "metricType": "DEBT_ISSUED_PAR",
                "metricValue": 80.0,
                "currency": "USD",
                "recordCount": 1,
                "entityResolutionState": "CANONICAL_V1_ENTITY_ID",
                "financialValueState": "MEASURED_PAR_AMOUNT",
                "rank": 2,
            },
        ],
        "sourceManifestations": [
            {"path": "data/canonical_v1/debt_instruments.csv", "sha256": "a" * 64}
        ],
        "methodology": {"identity": "canonical_v1 issuer_entity_id only"},
    }


def _snapshot():
    return make_snapshot(
        _ranking(),
        captured_at="2026-09-03T16:35:24+00:00",
        snapshot_id="debt-current",
        runtime_manifest={
            "state": "FROZEN",
            "producerCommit": "b" * 40,
            "files": [{"path": "leaderboards.py", "sha256": "c" * 64}],
        },
    )


@pytest.mark.unit
def test_scope_certifier_promotes_only_closed_snapshot():
    snapshot = _snapshot()
    assert certification_errors(snapshot, _scope()) == []
    certified = certify(snapshot, _scope(), certified_at="2026-09-13T18:00:00+00:00")
    assert certified["certificationState"] == "PASS"
    assert certified["certification"]["state"] == "PASS"
    assert certified["certification"]["zeroMaterialUnresolvedResidue"] is True
    assert certified["certification"]["ciExecutionPolicy"]["assertsPass"] is False
    assert certified["snapshotSha256"] != snapshot["snapshotSha256"]


@pytest.mark.unit
def test_unresolved_or_excluded_residue_blocks_certification():
    snapshot = _snapshot()
    snapshot["accounting"]["unresolvedRecords"] = 1
    from server.backend.leaderboard_history import snapshot_sha256
    snapshot["snapshotSha256"] = snapshot_sha256(snapshot)
    assert "accounting.unresolvedRecords" in certification_errors(snapshot, _scope())

    snapshot = _snapshot()
    snapshot["accounting"]["excludedRecords"] = 1
    snapshot["snapshotSha256"] = snapshot_sha256(snapshot)
    assert "accounting.excludedRecords" in certification_errors(snapshot, _scope())


@pytest.mark.unit
def test_name_only_identity_and_currency_drift_block_certification():
    snapshot = _snapshot()
    snapshot["rows"][0]["entityResolutionState"] = "NAME_ONLY"
    snapshot["rows"][0]["currency"] = "EUR"
    from server.backend.leaderboard_history import snapshot_sha256
    snapshot["snapshotSha256"] = snapshot_sha256(snapshot)
    errors = certification_errors(snapshot, _scope())
    assert "row.entityResolutionState" in errors
    assert "row.currency" in errors


@pytest.mark.unit
def test_category_outside_scope_cannot_be_certified():
    snapshot = _snapshot()
    snapshot["categoryId"] = "contract_award"
    from server.backend.leaderboard_history import snapshot_sha256
    snapshot["snapshotSha256"] = snapshot_sha256(snapshot)
    assert "scope.category" in certification_errors(snapshot, _scope())
