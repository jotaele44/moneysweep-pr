from __future__ import annotations

import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[1]
VECTOR = (
    ROOT / "data" / "manifests" / "capital_control" / "evtc_sec13f_certification_vector_v1.json"
)


def test_evtc_vector_declares_independent_zero_residue_pass() -> None:
    payload = json.loads(VECTOR.read_text(encoding="utf-8"))
    assert payload["state"] == "PASS"
    assert payload["promotion_state"] == "PROMOTION_ELIGIBLE"
    assert payload["parent_main_sha"] == "f5068c8e2583f790f945aa09903ddce312fad27d"
    assert payload["true_head_lock_main_sha"] == payload["parent_main_sha"]
    assert payload["parent_bpop_certification"] == "BPOP_SEC13F_8Q_v1_REFERENCE_ONLY_NOT_INHERITED"
    assert payload["parent_ofg_certification"] == "OFG_SEC13F_v1_REFERENCE_ONLY_NOT_INHERITED"
    assert payload["certification_inheritance"] == "FORBIDDEN"
    assert payload["issuer"] == {
        "ticker": "EVTC",
        "canonical_name": "EVERTEC, Inc.",
        "issuer_id": "ISSUER_CIK_0001559865",
        "cik": "0001559865",
        "cusip": "30040P103",
    }
    assert payload["negative_identity_gate"]["forbidden_ticker"] == "EVRI"
    assert payload["negative_identity_gate"]["near_name_identity"] == "FORBIDDEN"
    assert payload["provider_equivalence"] == "OPEN"
    assert (
        payload["aggregation_policy"] == "WHOLE_SOURCE_OBSERVATIONS_ONLY_NO_CROSS_HOLDER_SUMMATION"
    )
    assert payload["synthetic_row_identity"] == "FORBIDDEN"
    assert payload["deep_dive_promotion"] == "ELIGIBLE"
    assert payload["unresolved_residue"] == []
    assert payload["blockers"] == []


def test_evtc_vector_preserves_frozen_evidence_and_required_gates() -> None:
    payload = json.loads(VECTOR.read_text(encoding="utf-8"))
    evidence = payload["frozen_evidence"]
    assert evidence["snapshot_artifact_id"] == "9598537414"
    assert len(evidence["freeze_manifest_sha256"]) == 64
    assert len(evidence["denominators_sha256"]) == 64
    assert evidence["generalized_audit_result"] == "PASS"

    gates = set(payload["required_gates"])
    required = {
        "define_exact_EVTC_period_denominator",
        "freeze_exact_archive_denominator_and_member_hashes",
        "verify_EVTC_stable_issuer_binding",
        "verify_EVRI_does_not_satisfy_EVTC_identity",
        "preserve_whole_source_observations",
        "source_record_id_unique",
        "observation_id_unique",
        "filing_level_amendment_lineage_closed",
        "active_plus_superseded_arithmetic_closed",
        "exact_historical_share_denominator_each_certified_period",
        "issuer_percentage_arithmetic_closed",
        "provider_equivalence_OPEN",
        "zero_unresolved_residue_inside_claim",
        "independent_exact_head_CI_PASS",
        "exact_parent_and_merge_base_lock_PASS",
        "true_pr_head_sha_lock_PASS",
        "evidence_artifact_bound_to_true_pr_head",
    }
    assert required <= gates
