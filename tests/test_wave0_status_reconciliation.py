from __future__ import annotations

import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit
ROOT = Path(__file__).resolve().parents[1]

# This file mirrors long immutable status identifiers and generated-schema keys.
# Keep its assertion layout stable while Ruff linting and pytest remain active.
# fmt: off


def _read(path: str) -> dict:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def test_current_status_matches_authoritative_readiness() -> None:
    status = _read("reports/current_status.json")
    readiness = _read("reports/materialization_readiness.json")
    registry = status["source_registry_current"]
    assert registry["total_sources"] == readiness["total_sources"]
    assert (
        registry["source_ids_sha256"]
        == readiness["source_count_provenance"]["source_ids_sha256"]
    )
    for key in (
        "total_sources",
        "automatable_total",
        "automatable_ready",
        "queued_excluded_total",
        "queued_excluded",
    ):
        assert status["materialization_readiness_truth"][key] == readiness[key]


def test_status_records_pr448_postmerge_and_pr452_draft_state() -> None:
    status = _read("reports/current_status.json")
    assert status["schema_version"] == "moneysweep_current_status_v8"
    assert status["main_sha"] == "315520119c47b0f271f19531d53de8454d99f41a"
    assert status["active_pr"] is None
    merge = status["merge_record"]
    assert merge["pr_number"] == 448
    assert merge["state"] == "MERGED"
    assert merge["draft"] is False
    assert merge["merge_authorized"] is True
    assert merge["merge_completed"] is True
    assert merge["premerge_workflows"] == 17
    assert merge["premerge_workflows_successful"] == 17
    postmerge = status["wave0_ci_certification"]["postmerge_status_pr"]
    assert postmerge["number"] == 452
    assert postmerge["state"] == "OPEN_DRAFT"
    assert postmerge["input_workflows"] == 15
    assert postmerge["input_successful_workflows"] == 15


def test_coverage_preserves_certified_denominator_without_false_credit() -> None:
    coverage = _read("reports/current_status.json")["materialization_coverage"]
    snapshot = coverage["local_operator_snapshot"]
    # The operator corpus was measured against a 151-source registry. Additional
    # sources were registered afterwards, so the audit is stale relative to the
    # live registry: its own denominator is unchanged and its counts stay valid
    # for that denominator, but the two are no longer comparable. Re-measuring
    # needs an operator machine — this checkout has no such corpus, so the
    # snapshot must not be regenerated here.
    assert coverage["evidence_registry_total"] == 151
    readiness = _read("reports/materialization_readiness.json")
    assert coverage["current_registry_total"] == readiness["total_sources"]
    assert coverage["denominator_comparable"] is False
    assert coverage["denominator_drift_note"]
    assert coverage["probe_ran"] is False
    assert coverage["registry_digest_parity"] is False
    assert coverage["status_count_parity"] is True
    assert coverage["full_audit_rerun"] is False
    assert snapshot["fully_materialized"] == 67
    assert snapshot["partially_materialized"] == 11
    assert snapshot["not_materialized"] == 73
    assert snapshot["required_fully_materialized"] == 10
    assert snapshot["required_sources"] == 14
    assert snapshot["unadjudicated_orphan_rows"] == 0
    assert snapshot["unresolved_lineage_rows_within_derived_outputs"] == 0


def test_required_upload_receipt_awards_no_empty_source_credit() -> None:
    receipt = _read("reports/WAVE0_REQUIRED_EXPORT_INGESTION_RECEIPT_2026-07-30.json")
    required = receipt["required_source_result"]
    for source_id in ("cor3", "hud_drgr_authorized", "pr_cabilderos", "prasa"):
        assert required[source_id]["positive_rows"] == 0
        assert required[source_id]["materialization_credit"] is False
    assert required["required_fully_materialized_before"] == 10
    assert required["required_fully_materialized_after"] == 10
    assert receipt["execution_boundary"]["raw_files_committed"] is False
    assert receipt["full_151_source_audit"]["status"] == "NOT_RERUN_PARTIAL_UPLOAD_SET"


def test_entity_comparison_uses_actual_staging_key_and_is_complete() -> None:
    report = _read("reports/entity_product_comparison.json")
    assert report["status"] == "COMPLETE"
    assert report["left"]["stable_key_column"] == "entity_key"
    assert report["right"]["stable_key_column"] == "normalized_name"
    assert report["left"]["row_count"] == 104280
    assert report["right"]["row_count"] == 104280
    assert report["stable_key_overlap"]["intersection_unique"] == 104280
    assert report["stable_key_overlap"]["union_unique"] == 104280
    assert report["stable_key_overlap"]["overlap_rate_max_denominator"] == 1.0
    assert report["stable_key_overlap"]["jaccard_rate"] == 1.0
    assert report["duplicate_status"] == "OVERLAPPING_DERIVED_PRODUCTS"
    assert report["identical_file"] is False
    assert report["semantic_duplicate"] is False


def test_gap_and_output_ownership_adjudication_has_complete_lineage() -> None:
    adjudication = _read("reports/WAVE0_REQUIRED_GAP_AND_ORPHAN_ADJUDICATION.json")
    required = {
        row["source_id"]: row
        for row in adjudication["required_source_adjudication"]
    }
    assert set(required) == {
        "cor3",
        "hud_drgr_authorized",
        "pr_cabilderos",
        "prasa",
    }
    assert all(row["materialization_credit"] is False for row in required.values())
    derived = {
        row["file"]: row
        for row in adjudication["derived_output_adjudication"]
    }
    assert sum(row["rows"] for row in derived.values()) == 212930
    assert all(
        row["source_materialization_credit"] is False
        for row in derived.values()
    )
    assert derived["entity_master.csv"]["producer"] == "scripts/build_unified_master.py"
    assert derived["entity_master.csv"]["producer_status"] == "CONFIRMED"
    assert sum(row["producer_status"] == "CONFIRMED" for row in derived.values()) == 6
    assert adjudication["row_accounting"]["unresolved_lineage_rows_within_derived_outputs"] == 0
    assert adjudication["boundaries"]["all_derived_output_lineage_certified"] is True


def test_adjudicated_row_buckets_have_exact_parity_without_double_counting() -> None:
    rows = _read("reports/WAVE0_REQUIRED_GAP_AND_ORPHAN_ADJUDICATION.json")[
        "row_accounting"
    ]
    assert rows["registry_declared_rows"] == 849898
    assert rows["derived_output_rows"] == 212930
    assert rows["intermediate_rows"] == 120737
    assert rows["unadjudicated_orphan_rows"] == 0
    assert (
        rows["registry_declared_rows"]
        + rows["derived_output_rows"]
        + rows["intermediate_rows"]
        + rows["unadjudicated_orphan_rows"]
        == rows["total_rows_on_disk"]
        == 1183565
    )
    assert rows["parity"] is True
    assert rows["double_counting_detected"] is False


def test_status_preserves_historical_blob_reference() -> None:
    evidence = _read("reports/current_status.json")["historical_status_evidence"]
    assert evidence["path_at_base"] == "reports/current_status.json"
    assert evidence["blob_sha"] == "b175df73deb6ecf5bbf0d0040b89ca75f5d1e10c"


def test_roadmaps_record_entity_result_without_opening_production() -> None:
    detailed = (ROOT / "docs/ROAD_TO_100.md").read_text(encoding="utf-8")
    normalized = (ROOT / "docs/ROAD_TO_100_NORMALIZED.md").read_text(
        encoding="utf-8"
    )
    for text in (detailed, normalized):
        compact = text.replace(" ", "")
        assert "#452" in text
        assert "10/14" in compact
        assert "104,280" in text
        assert "OVERLAPPING_DERIVED_PRODUCTS" in text
        assert "NON_PRODUCTION_DIAGNOSTIC" in text
        assert "Unadjudicated orphan rows | 0" in text
        assert "Derived rows with unresolved lineage | 0" in text


def test_preservation_flags_remain_fail_closed() -> None:
    preservation = _read("reports/current_status.json")["preservation"]
    assert preservation["pr_448_draft"] is False
    assert preservation["pr_448_merge_authorized"] is True
    assert preservation["pr_448_merge_completed"] is True
    assert preservation["pr_452_draft"] is True
    assert preservation["pr_452_merge_authorized"] is False
    assert preservation["direct_main_write_authorized"] is False
    assert preservation["live_fetch_authorized"] is False
    assert preservation["credential_automation_authorized"] is False
    assert preservation["data_promotion_authorized"] is False
    assert preservation["production_activation_authorized"] is False
    assert preservation["force_push_authorized"] is False
    assert preservation["history_rewrite_authorized"] is False
    assert preservation["raw_operator_files_committed"] is False


# fmt: on
