"""R4.9B partial diagnostic rebuild retry orchestration."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from contract_sweeper.pipeline.acquisition_package import (
    read_csv,
    read_json,
    safe_int,
    utc_now,
    write_csv,
    write_json,
)
from contract_sweeper.pipeline.partial_master_rebuild import run_partial_master_rebuild


def _input_rows_from_materialization(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        out.append(
            {
                "expected_input": str(row.get("target_output_path", "")).strip(),
                "source_dataset": str(row.get("source_system", "")).strip(),
                "mapped_rel": str(row.get("target_output_path", "")).strip(),
                "mapped_abs": str(row.get("target_output_abs", "")).strip(),
                "mapping_mode": "r4_9b_materialization_scan",
                "input_status": str(row.get("materialization_status", "")).strip() or "unknown",
                "row_count": safe_int(row.get("target_row_count")),
                "sha256": str(row.get("target_sha256", "")).strip(),
                "source_system": str(row.get("source_system", "")).strip(),
                "source_file": str(row.get("source_file", "")).strip(),
                "source_manifest_path": str(row.get("manifest_path", "")).strip(),
                "target_output_path": str(row.get("target_output_path", "")).strip(),
                "lineage_path": str(row.get("target_output_path", "")).strip(),
                "reason": str(row.get("blocker_reason", "")).strip(),
            }
        )
    return out


def _lineage_rows_from_materialization(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        out.append(
            {
                "expected_input": str(row.get("target_output_path", "")).strip(),
                "source_system": str(row.get("source_system", "")).strip(),
                "source_file": str(row.get("source_file", "")).strip(),
                "source_manifest_path": str(row.get("manifest_path", "")).strip(),
                "target_output_path": str(row.get("target_output_path", "")).strip(),
                "lineage_path": str(row.get("target_output_path", "")).strip(),
                "mapped_rel": str(row.get("target_output_path", "")).strip(),
                "mapped_abs": str(row.get("target_output_abs", "")).strip(),
                "mapping_mode": "r4_9b_materialization_scan",
                "input_status": str(row.get("materialization_status", "")).strip(),
                "row_count": safe_int(row.get("target_row_count")),
                "sha256": str(row.get("target_sha256", "")).strip(),
            }
        )
    return out


def run_partial_rebuild_retry(root: Path, materialization_status: dict[str, Any]) -> dict[str, Any]:
    root = Path(root)
    exports_dir = root / "data" / "exports"
    review_dir = root / "data" / "review_queue"

    rebuild_status = read_json(exports_dir / "rebuild_status.json")
    manifest_rows = read_csv(exports_dir / "validated_source_manifest_inventory_r4_8i.csv")
    materialization_rows = read_csv(exports_dir / "source_materialization_results_r4_9b.csv")
    materialization_blockers = read_csv(review_dir / "source_materialization_blockers_r4_9b.csv")

    manifest_records_checked = safe_int(materialization_status.get("r4_9b_manifest_records_checked"))
    files_materialized = safe_int(materialization_status.get("r4_9b_files_materialized"))
    files_hash_validated = safe_int(materialization_status.get("r4_9b_files_hash_validated"))
    materialization_blocker_count = safe_int(materialization_status.get("r4_9b_materialization_blockers"))
    forbidden_artifact_usage = bool(materialization_status.get("r4_9b_forbidden_artifact_usage", False))

    rebuild_attempted = False
    rebuild_succeeded = False
    output_rows = 0
    unique_entities = 0
    source_lineage_coverage = 0.0
    output_status = "BLOCKED_DIAGNOSTIC"
    retry_reason = ""

    if files_hash_validated > 0 and not forbidden_artifact_usage:
        retry = run_partial_master_rebuild(root)
        rebuild_attempted = bool(retry.get("r4_9a_rebuild_attempted", False))
        rebuild_succeeded = bool(retry.get("r4_9a_rebuild_succeeded", False))
        output_rows = safe_int(retry.get("r4_9a_output_rows"))
        unique_entities = safe_int(retry.get("r4_9a_unique_entities"))
        source_lineage_coverage = float(retry.get("r4_9a_source_lineage_coverage", 0.0) or 0.0)
        output_status = str(retry.get("r4_9a_output_status", "BLOCKED_DIAGNOSTIC"))
    else:
        if forbidden_artifact_usage:
            retry_reason = "forbidden_artifact_usage_detected"
        elif files_hash_validated <= 0:
            retry_reason = "no_hash_validated_physical_sources_available"
        else:
            retry_reason = "retry_blocked_unknown_reason"

    if rebuild_attempted:
        input_rows = read_csv(exports_dir / "partial_master_rebuild_inputs_r4_9a.csv")
        lineage_rows = read_csv(exports_dir / "partial_master_rebuild_lineage_report_r4_9a.csv")
    else:
        input_rows = _input_rows_from_materialization(materialization_rows)
        lineage_rows = _lineage_rows_from_materialization(materialization_rows)

    blocker_rows: list[dict[str, Any]] = []
    for row in materialization_blockers:
        blocker_rows.append(
            {
                "blocker_type": "source_materialization",
                "source_system": str(row.get("source_system", "")).strip(),
                "expected_input": str(row.get("target_output_path", "")).strip(),
                "reason": str(row.get("blocker_reason", "")).strip(),
                "next_action": str(row.get("next_action", "manual_or_external_acquisition")).strip(),
            }
        )
    if retry_reason:
        blocker_rows.append(
            {
                "blocker_type": "partial_rebuild_retry",
                "source_system": "system",
                "expected_input": "partial_diagnostic_retry",
                "reason": retry_reason,
                "next_action": "preserve_blocked_diagnostic",
            }
        )

    # Gate checks
    all_manifest_records_checked = manifest_records_checked == len(manifest_rows)
    non_materialized_count = max(manifest_records_checked - files_materialized, 0)
    non_materialized_queued = materialization_blocker_count >= non_materialized_count
    materialized_hash_valid = files_hash_validated == files_materialized
    rebuild_state_valid = bool(
        (rebuild_attempted and (rebuild_succeeded or output_status == "BLOCKED_DIAGNOSTIC"))
        or (not rebuild_attempted and retry_reason)
    )

    production_status = "NON_PRODUCTION_DIAGNOSTIC"
    row_fabrication_policy = str(
        rebuild_status.get("row_fabrication_policy") or "FORBIDDEN_NO_SYNTHETIC_ROWS"
    )
    phase_7_8_blocked = bool(rebuild_status.get("phase_7_8_blocked", True))

    gate_passed = bool(
        all_manifest_records_checked
        and materialized_hash_valid
        and non_materialized_queued
        and rebuild_state_valid
        and not forbidden_artifact_usage
        and production_status == "NON_PRODUCTION_DIAGNOSTIC"
        and row_fabrication_policy == "FORBIDDEN_NO_SYNTHETIC_ROWS"
        and phase_7_8_blocked
    )

    status_payload = {
        "generated_at": utc_now(),
        "r4_9b_gate_passed": gate_passed,
        "r4_9b_manifest_records_checked": manifest_records_checked,
        "r4_9b_files_materialized": files_materialized,
        "r4_9b_files_hash_validated": files_hash_validated,
        "r4_9b_materialization_blockers": materialization_blocker_count,
        "r4_9b_rebuild_attempted": rebuild_attempted,
        "r4_9b_rebuild_succeeded": rebuild_succeeded,
        "r4_9b_output_rows": output_rows,
        "r4_9b_unique_entities": unique_entities,
        "r4_9b_source_lineage_coverage": round(float(source_lineage_coverage), 4),
        "r4_9b_output_status": output_status,
        "production_status": production_status,
        "r4_9b_forbidden_artifact_usage": forbidden_artifact_usage,
        "row_fabrication_policy": row_fabrication_policy,
        "phase_7_8_blocked": phase_7_8_blocked,
    }

    write_json(exports_dir / "partial_rebuild_retry_status_r4_9b.json", status_payload)
    write_csv(
        exports_dir / "partial_rebuild_retry_inputs_r4_9b.csv",
        input_rows,
        [
            "expected_input",
            "source_dataset",
            "mapped_rel",
            "mapped_abs",
            "mapping_mode",
            "input_status",
            "row_count",
            "sha256",
            "source_system",
            "source_file",
            "source_manifest_path",
            "target_output_path",
            "lineage_path",
            "reason",
        ],
    )
    write_csv(
        exports_dir / "partial_rebuild_retry_lineage_report_r4_9b.csv",
        lineage_rows,
        [
            "expected_input",
            "source_system",
            "source_file",
            "source_manifest_path",
            "target_output_path",
            "lineage_path",
            "mapped_rel",
            "mapped_abs",
            "mapping_mode",
            "input_status",
            "row_count",
            "sha256",
        ],
    )
    write_csv(
        review_dir / "partial_rebuild_retry_blockers_r4_9b.csv",
        blocker_rows,
        ["blocker_type", "source_system", "expected_input", "reason", "next_action"],
    )

    rebuild_status.update(
        {
            "r4_9b_generated_at": status_payload["generated_at"],
            "r4_9b_gate_passed": gate_passed,
            "r4_9b_manifest_records_checked": manifest_records_checked,
            "r4_9b_files_materialized": files_materialized,
            "r4_9b_files_hash_validated": files_hash_validated,
            "r4_9b_materialization_blockers": materialization_blocker_count,
            "r4_9b_rebuild_attempted": rebuild_attempted,
            "r4_9b_rebuild_succeeded": rebuild_succeeded,
            "r4_9b_output_rows": output_rows,
            "r4_9b_unique_entities": unique_entities,
            "r4_9b_source_lineage_coverage": round(float(source_lineage_coverage), 4),
            "r4_9b_output_status": output_status,
            "r4_9b_forbidden_artifact_usage": forbidden_artifact_usage,
            "production_status": production_status,
            "row_fabrication_policy": row_fabrication_policy,
            "phase_7_8_blocked": phase_7_8_blocked,
        }
    )
    write_json(exports_dir / "rebuild_status.json", rebuild_status)

    return status_payload
