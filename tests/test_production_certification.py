import csv
import subprocess
from pathlib import Path

import pytest

from tools.audit_materialization_coverage import build as build_coverage_audit
from tools.certify_production import build_report
from tools.operator_corpus_common import load_sources, source_ids_digest

pytestmark = pytest.mark.unit
ROOT = Path(__file__).resolve().parents[1]
HISTORICAL_MAIN_SHA = "ba0c0d11a011669a5d487dc116274491449d4b72"
HISTORICAL_SOURCE_IDS_SHA256 = "353995f4595fde0f7643ff8d9987154bcd230abe30037cdcbe6e3abd7f4233d1"
CURRENT_SOURCE_IDS_SHA256 = "4c551385f00ca6df4332ee1643d0ef7a6ab85172632d945d35be285cd94f5826"
HISTORICAL_SNAPSHOT_ROOT = (
    ROOT / "certification_scopes/reconciliation-20260913-7b467ff/inputs/A"
)


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
        generated_at="2026-09-13T17:30:00-04:00",
    )


def _gates(report: dict) -> dict[str, dict]:
    return {gate["id"]: gate for gate in report["gates"]}


def _current_status_rows() -> list[dict[str, str]]:
    path = ROOT / "reports/source_registry_status.csv"
    with path.open("r", encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def test_current_evidence_audit_uses_exact_live_denominator_and_converged_profile() -> None:
    report = _report()
    gates = _gates(report)
    sources, _ = load_sources(ROOT)

    assert report["scope"]["commit_sha"] == _head()
    assert report["scope"]["commit_sha"] == report["scope"]["checkout_head_sha"]
    assert report["audit_implementation"]["commit_sha"] == _head()
    assert len(sources) == 164
    assert report["scope"]["registry_total_sources"] == len(sources)
    assert report["scope"]["registry_required_sources"] == 16
    assert source_ids_digest(sources) == CURRENT_SOURCE_IDS_SHA256
    assert report["scope"]["registry_source_ids_sha256"] == CURRENT_SOURCE_IDS_SHA256
    assert len(report["source_universe"]["source_ledger"]) == len(sources)
    assert report["certification_state"] == "NON_PRODUCTION_DIAGNOSTIC"
    assert report["production_eligible"] is False

    g0 = gates["G0_SCOPE_FREEZE"]
    assert g0["state"] == "PASS"
    assert g0["evidence"]["runtime_certification_source_id_delta"] == []
    assert g0["evidence"]["runtime_certification_definition_delta"] == []
    assert g0["evidence"]["registry_profile_blockers"] == []
    assert g0["blockers"] == []

    assert gates["G1_CONTROL_PLANE_RECONCILIATION"]["state"] == "PASS"
    assert gates["G2_STRICT_PREFLIGHT"]["state"] == "OPEN"
    assert gates["G3_REQUIRED_SOURCE_MATERIALIZATION"]["state"] == "FAIL"
    assert gates["G4_FULL_SOURCE_CLASSIFICATION"]["state"] == "PASS"
    assert gates["G5_AUTOMATABLE_EXECUTION"]["state"] == "FAIL"
    assert gates["G6_SOURCE_VALIDATION_AND_COVERAGE_CONTRACTS"]["state"] == "FAIL"
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


def test_required_source_residue_matches_current_status_rows_exactly() -> None:
    report = _report()
    gate = _gates(report)["G3_REQUIRED_SOURCE_MATERIALIZATION"]
    rows = _current_status_rows()
    expected = {
        row["source_id"]
        for row in rows
        if row["required"].lower() == "true" and row["pipeline_status"] != "fully_materialized"
    }

    assert gate["evidence"]["required_status_counts"] == {
        "fully_materialized": 11,
        "not_materialized": 3,
        "partially_materialized": 2,
    }
    assert {row["source_id"] for row in gate["evidence"]["required_blockers"]} == expected
    assert expected == {
        "usaspending_prime",
        "hud_drgr_authorized",
        "prasa",
        "campaign_finance_entities",
        "campaign_finance_materialization_gate",
    }


def test_entity_policy_remains_conservative() -> None:
    report = _report()
    gate = _gates(report)["G7_ENTITY_RESOLUTION"]

    assert gate["evidence"]["blocking_review_count"] == 0
    assert gate["evidence"]["canonical_review_queue_open_rows"] == 0
    assert gate["evidence"]["canonical_graph_review_queue_open"] == 0
    assert gate["evidence"]["policy"]["name_only_resolution_allowed"] is False
    assert gate["evidence"]["policy"]["confidence_threshold_lowered"] is False


def test_current_completeness_is_not_promoted() -> None:
    report = _report()
    gates = _gates(report)
    completeness = report["source_universe"]["completeness_matrix"]

    assert completeness["total_sources"] == 164
    assert completeness["by_materialization_status"] == {
        "fully_materialized": 17,
        "not_materialized": 144,
        "partially_materialized": 3,
    }
    assert completeness["contracted_sources"] == 23
    assert completeness["by_coverage_status"] == {
        "below_contract": 3,
        "meets_contract": 3,
        "uncontracted": 141,
        "unverifiable": 17,
    }
    assert gates["G8_PROVENANCE_AND_LINEAGE"]["state"] == "BLOCKED"
    assert gates["G9_CANONICAL_MASTER_INVARIANTS"]["state"] == "BLOCKED"
    assert gates["G11_PRODUCTION_EXPORT_AND_FEDERATION"]["state"] == "BLOCKED"


def test_lineage_auditor_includes_effective_registry_inputs_without_granting_authority() -> None:
    audit = build_coverage_audit(ROOT, operator_corpus_authoritative=False)

    assert audit["local_truth_summary"]["total_sources"] == 164
    assert audit["local_truth_summary"]["required_sources"] == 16
    assert audit["audit_scope"]["operator_corpus_authoritative"] is False
    assert audit["processed_file_inventory"]["orphan_rows"] is None
    registry_paths = set(audit["audit_scope"]["registry_paths"])
    assert "registries/source_registry.json" in registry_paths
    assert "registries/source_registry_extensions/fomb.json" in registry_paths
    assert "registries/source_registry_extensions/campaign_finance_completion.json" in registry_paths
    assert "registries/source_registry_extensions/nara_nextgen.json" in registry_paths
    assert "registries/source_registry_extensions/sec_ownership_hardening_v0_3.json" in registry_paths
    assert "registries/source_registry_overrides/wave0_provenance_corrections.json" in registry_paths
    assert "registries/source_registry.yaml" not in registry_paths


def test_current_and_historical_registry_identities_are_separate_and_preserved() -> None:
    current_sources, _ = load_sources(ROOT)
    historical_sources, _ = load_sources(HISTORICAL_SNAPSHOT_ROOT)

    assert len(current_sources) == 164
    assert source_ids_digest(current_sources) == CURRENT_SOURCE_IDS_SHA256
    assert len(historical_sources) == 162
    assert source_ids_digest(historical_sources) == HISTORICAL_SOURCE_IDS_SHA256
    current_ids = {source["source_id"] for source in current_sources}
    historical_ids = {source["source_id"] for source in historical_sources}
    assert historical_ids - current_ids == set()
    assert current_ids - historical_ids == {"pr_fomb", "pr_fomb_special_reports"}


def test_readiness_population_arithmetic_closes_without_hardcoded_automatable_count() -> None:
    report = _report()
    universe = report["source_universe"]
    assert universe["automatable_total"] == 116
    assert universe["queued_excluded_total"] == 48
    assert universe["automatable_total"] + universe["queued_excluded_total"] == 164


def test_bare_authority_assertion_cannot_unlock_lineage() -> None:
    audit = build_coverage_audit(ROOT, operator_corpus_authoritative=True)

    assert audit["audit_scope"]["operator_corpus_authoritative"] is False
    assert "bare_authority_assertion_not_evidence" in audit["audit_scope"]["authority_blockers"]
    assert audit["processed_file_inventory"]["orphan_rows"] is None
    assert audit["processed_file_inventory"]["orphan_file_count"] is None
