import subprocess
from pathlib import Path

import pytest

from tools.audit_materialization_coverage import build as build_coverage_audit
from tools.certify_production import build_report
from tools.operator_corpus_common import load_sources, source_ids_digest

pytestmark = pytest.mark.unit
ROOT = Path(__file__).resolve().parents[1]
HISTORICAL_MAIN_SHA = "ba0c0d11a011669a5d487dc116274491449d4b72"
CANONICAL_SOURCE_IDS_SHA256 = "353995f4595fde0f7643ff8d9987154bcd230abe30037cdcbe6e3abd7f4233d1"


def _head() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _report() -> dict:
    head = _head()
    return build_report(
        root=ROOT,
        scope_sha=head,
        implementation_sha=head,
        run_preflight=False,
        generated_at="2026-08-28T22:30:00-04:00",
    )


def _gates(report: dict) -> dict[str, dict]:
    return {gate["id"]: gate for gate in report["gates"]}


def test_current_evidence_audit_is_fail_closed_and_denominator_exact() -> None:
    report = _report()
    gates = _gates(report)

    assert report["scope"]["commit_sha"] == _head()
    assert report["scope"]["commit_sha"] == report["scope"]["checkout_head_sha"]
    assert report["audit_implementation"]["commit_sha"] == _head()
    assert report["scope"]["registry_total_sources"] == 162
    assert report["scope"]["registry_required_sources"] == 16
    assert report["scope"]["registry_source_ids_sha256"] == CANONICAL_SOURCE_IDS_SHA256
    assert "certification_config" in report["input_manifest"]
    assert len(report["source_universe"]["source_ledger"]) == 162
    assert report["certification_state"] == "NON_PRODUCTION_DIAGNOSTIC"
    assert report["production_eligible"] is False

    assert gates["G0_SCOPE_FREEZE"]["state"] == "PASS"
    assert gates["G1_CONTROL_PLANE_RECONCILIATION"]["state"] == "PASS"
    assert gates["G2_STRICT_PREFLIGHT"]["state"] == "OPEN"
    assert gates["G3_REQUIRED_SOURCE_MATERIALIZATION"]["state"] == "FAIL"
    assert gates["G4_FULL_SOURCE_CLASSIFICATION"]["state"] == "PASS"
    assert gates["G5_AUTOMATABLE_EXECUTION"]["state"] == "FAIL"
    assert gates["G6_SOURCE_VALIDATION_AND_COVERAGE_CONTRACTS"]["state"] == "FAIL"
    assert gates["G7_ENTITY_RESOLUTION"]["state"] == "PASS"
    assert gates["G8_PROVENANCE_AND_LINEAGE"]["state"] == "BLOCKED"
    assert gates["G9_CANONICAL_MASTER_INVARIANTS"]["state"] == "BLOCKED"
    assert gates["G10_FRESHNESS_AND_UNIVERSE_COMPLETENESS"]["state"] == "FAIL"
    assert gates["G11_PRODUCTION_EXPORT_AND_FEDERATION"]["state"] == "BLOCKED"
    assert gates["G12_RELEASE_CERTIFICATION"]["state"] == "BLOCKED"


def test_scope_mismatch_fails_closed() -> None:
    report = build_report(
        root=ROOT,
        scope_sha=HISTORICAL_MAIN_SHA,
        implementation_sha=_head(),
        run_preflight=False,
    )
    assert _gates(report)["G0_SCOPE_FREEZE"]["state"] == "FAIL"
    assert report["production_eligible"] is False


def test_required_source_residue_is_exact_for_current_registry() -> None:
    report = _report()
    gate = _gates(report)["G3_REQUIRED_SOURCE_MATERIALIZATION"]

    assert gate["evidence"]["required_status_counts"] == {
        "fully_materialized": 8,
        "not_materialized": 7,
        "partially_materialized": 1,
    }
    assert {row["source_id"] for row in gate["evidence"]["required_blockers"]} == {
        "usaspending_prime",
        "cor3",
        "hud_drgr_authorized",
        "prasa",
        "oficina_contralor",
        "pr_cabilderos",
        "campaign_finance_entities",
        "campaign_finance_materialization_gate",
    }


def test_entity_advisory_residue_does_not_masquerade_as_unresolved_identity() -> None:
    report = _report()
    gate = _gates(report)["G7_ENTITY_RESOLUTION"]

    assert gate["state"] == "PASS"
    assert gate["evidence"]["open_review_count"] == 24
    assert gate["evidence"]["advisory_low_confidence_count"] == 24
    assert gate["evidence"]["blocking_review_count"] == 0
    assert gate["evidence"]["canonical_review_queue_open_rows"] == 0
    assert gate["evidence"]["canonical_graph_review_queue_open"] == 0
    assert gate["blockers"] == []
    assert gate["evidence"]["policy"]["name_only_resolution_allowed"] is False
    assert gate["evidence"]["policy"]["confidence_threshold_lowered"] is False


def test_current_completeness_is_not_promoted() -> None:
    report = _report()
    gates = _gates(report)

    completeness = report["source_universe"]["completeness_matrix"]
    assert completeness["total_sources"] == 162
    assert completeness["by_materialization_status"] == {
        "fully_materialized": 11,
        "not_materialized": 149,
        "partially_materialized": 2,
    }
    assert completeness["contracted_sources"] == 23
    assert completeness["by_coverage_status"] == {
        "below_contract": 4,
        "meets_contract": 2,
        "uncontracted": 139,
        "unverifiable": 17,
    }

    assert gates["G8_PROVENANCE_AND_LINEAGE"]["state"] == "BLOCKED"
    assert (
        gates["G9_CANONICAL_MASTER_INVARIANTS"]["evidence"]["canonical_graph_gate"]
        == "NON_PRODUCTION_DIAGNOSTIC"
    )
    assert (
        gates["G11_PRODUCTION_EXPORT_AND_FEDERATION"]["evidence"]["production_status"]
        == "NON_PRODUCTION_DIAGNOSTIC"
    )


def test_lineage_auditor_includes_core_and_extension_registries() -> None:
    audit = build_coverage_audit(ROOT, operator_corpus_authoritative=False)

    assert audit["local_truth_summary"]["total_sources"] == 162
    assert audit["local_truth_summary"]["required_sources"] == 16
    assert audit["audit_scope"]["operator_corpus_authoritative"] is False
    assert audit["processed_file_inventory"]["orphan_rows"] is None
    registry_paths = set(audit["audit_scope"]["registry_paths"])
    assert "registries/source_registry.yaml" in registry_paths
    assert (
        "registries/source_registry_extensions/campaign_finance_completion.json" in registry_paths
    )
    assert "registries/source_registry_extensions/nara_nextgen.json" in registry_paths
    assert (
        "registries/source_registry_extensions/sec_ownership_hardening_v0_3.json" in registry_paths
    )


def test_operator_corpus_digest_matches_existing_162_source_identity() -> None:
    sources, _ = load_sources(ROOT)
    assert len(sources) == 162
    assert source_ids_digest(sources) == CANONICAL_SOURCE_IDS_SHA256


def test_bare_authority_assertion_cannot_unlock_lineage() -> None:
    audit = build_coverage_audit(ROOT, operator_corpus_authoritative=True)

    assert audit["audit_scope"]["operator_corpus_authoritative"] is False
    assert "bare_authority_assertion_not_evidence" in audit["audit_scope"]["authority_blockers"]
    assert audit["processed_file_inventory"]["orphan_rows"] is None
    assert audit["processed_file_inventory"]["orphan_file_count"] is None
