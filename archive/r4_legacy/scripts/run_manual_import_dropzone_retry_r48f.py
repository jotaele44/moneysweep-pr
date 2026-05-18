"""Run R4.8F manual-import dropzone validation and patch retries."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from contract_sweeper.pipeline.endpoint_patch_retry import run_endpoint_patch_retries
from contract_sweeper.pipeline.manual_import_dropzone import (
    read_csv,
    read_json,
    safe_int,
    write_csv,
    write_json,
    process_manual_import_dropzones,
    utc_now,
)
from contract_sweeper.pipeline.producer_patch_retry import run_producer_patch_retries


def _combine_validated_manifests(
    *,
    existing_rows: list[dict[str, str]],
    new_rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int, int, int]:
    combined_by_target: dict[str, dict[str, Any]] = {}
    for row in existing_rows:
        target = str(row.get("target_output_path", "")).strip()
        if not target:
            continue
        combined_by_target[target] = dict(row)

    unique_new_by_target: dict[str, dict[str, Any]] = {}
    for row in new_rows:
        target = str(row.get("target_output_path", "")).strip()
        if not target:
            continue
        unique_new_by_target[target] = dict(row)
        combined_by_target[target] = dict(row)

    combined_rows = list(combined_by_target.values())
    combined_rows.sort(key=lambda row: str(row.get("target_output_path", "")))

    new_rows_ingested = sum(safe_int(row.get("row_count")) for row in unique_new_by_target.values())
    new_staged = len(unique_new_by_target)
    new_manifests = len(unique_new_by_target)
    return combined_rows, new_rows_ingested, new_staged, new_manifests


def _manifest_integrity_ok(rows: list[dict[str, Any]]) -> bool:
    if not rows:
        return True
    for row in rows:
        if safe_int(row.get("row_count")) <= 0:
            return False
        if not str(row.get("sha256", "")).strip():
            return False
        if not str(row.get("target_output_path", "")).strip():
            return False
    return True


def run_manual_import_dropzone_retry(
    root: Path,
    *,
    command_timeout_seconds: int = 30,
) -> dict[str, Any]:
    root = Path(root)
    exports_dir = root / "data" / "exports"
    review_dir = root / "data" / "review_queue"

    manual_package = read_json(exports_dir / "manual_fallback_package_r4_8e.json")
    manual_inventory_r48e = read_csv(exports_dir / "manual_fallback_inventory_r4_8e.csv")
    endpoint_report_r48e = read_csv(exports_dir / "endpoint_resolution_report_r4_8e.csv")
    producer_report_r48e = read_csv(exports_dir / "producer_failure_resolution_report_r4_8e.csv")
    manual_required_r48e = read_csv(review_dir / "manual_files_required_r4_8e.csv")
    endpoint_followup_r48e = read_csv(review_dir / "endpoint_followup_required_r4_8e.csv")
    producer_remaining_r48e = read_csv(review_dir / "producer_patch_remaining_r4_8e.csv")
    retry_order_r48e = read_csv(review_dir / "backfill_retry_order_r4_8e.csv")
    manifests_r48d = read_csv(exports_dir / "validated_source_manifest_inventory_r4_8d.csv")
    status_r48d = read_json(exports_dir / "targeted_backfill_retry_status_r4_8d.json")
    rebuild_status = read_json(exports_dir / "rebuild_status.json")

    manual_inventory_r48f, manual_still_required_r48f, manual_new_manifests, manual_metrics, manual_forbidden = (
        process_manual_import_dropzones(
            root,
            manual_rows=manual_required_r48e,
        )
    )

    endpoint_report_r48f, endpoint_remaining_r48f, endpoint_new_manifests, endpoint_metrics, endpoint_forbidden = (
        run_endpoint_patch_retries(
            root,
            endpoint_rows=endpoint_followup_r48e,
            manual_rows=manual_required_r48e,
            command_timeout_s=max(1, int(command_timeout_seconds)),
        )
    )

    producer_report_r48f, producer_remaining_r48f, producer_new_manifests, producer_metrics, producer_forbidden = (
        run_producer_patch_retries(
            root,
            producer_rows=producer_remaining_r48e,
            manual_rows=manual_required_r48e,
            command_timeout_s=max(1, int(command_timeout_seconds)),
        )
    )

    all_new_manifests = manual_new_manifests + endpoint_new_manifests + producer_new_manifests
    manifests_r48f, new_rows_ingested, new_staged, new_new_manifests = _combine_validated_manifests(
        existing_rows=manifests_r48d,
        new_rows=all_new_manifests,
    )

    base_rows_ingested = safe_int(
        status_r48d.get("r4_8d_rows_ingested", rebuild_status.get("r4_8d_rows_ingested", 0))
    )
    base_staged = safe_int(
        status_r48d.get(
            "r4_8d_production_inputs_staged",
            rebuild_status.get("r4_8d_production_inputs_staged", 0),
        )
    )
    base_manifests = safe_int(
        status_r48d.get(
            "r4_8d_validated_source_manifests_written",
            rebuild_status.get("r4_8d_validated_source_manifests_written", len(manifests_r48d)),
        )
    )

    total_rows_ingested = base_rows_ingested + new_rows_ingested
    total_staged = base_staged + new_staged
    total_manifests = base_manifests + new_new_manifests

    row_fabrication_policy = str(
        rebuild_status.get("row_fabrication_policy")
        or status_r48d.get("row_fabrication_policy")
        or "FORBIDDEN_NO_SYNTHETIC_ROWS"
    )
    phase_7_8_blocked = bool(
        rebuild_status.get("phase_7_8_blocked", status_r48d.get("phase_7_8_blocked", True))
    )

    forbidden_artifact_usage = bool(
        manual_forbidden
        or endpoint_forbidden
        or producer_forbidden
        or bool(manual_package.get("forbidden_artifact_usage"))
    )

    manual_sources_checked = manual_metrics["manual_sources_checked"]
    manual_files_found = manual_metrics["manual_files_found"]
    manual_files_validated = manual_metrics["manual_files_validated"]
    manual_files_still_required = manual_metrics["manual_files_still_required"]

    endpoint_followups_reviewed = endpoint_metrics["endpoint_followups_reviewed"]
    endpoint_patches_applied = endpoint_metrics["endpoint_patches_applied"]
    endpoint_retries_attempted = endpoint_metrics["endpoint_retries_attempted"]
    endpoint_retries_successful = endpoint_metrics["endpoint_retries_successful"]

    producer_failures_reviewed = producer_metrics["producer_failures_reviewed"]
    producer_patches_applied = producer_metrics["producer_patches_applied"]
    producer_retries_attempted = producer_metrics["producer_retries_attempted"]
    producer_retries_successful = producer_metrics["producer_retries_successful"]

    all_manual_checked = manual_sources_checked == len(manual_required_r48e)
    manual_found_accounted = (manual_files_found - manual_files_validated) >= 0
    manual_required_queued = manual_files_still_required >= (len(manual_required_r48e) - manual_files_validated)
    endpoint_classified = all(
        bool(str(row.get("endpoint_classification", "")).strip())
        and bool(str(row.get("next_action", "")).strip())
        for row in endpoint_report_r48f
    )
    producer_classified = all(
        bool(str(row.get("producer_classification", "")).strip())
        and bool(str(row.get("next_action", "")).strip())
        for row in producer_report_r48f
    )
    manifest_integrity_ok = _manifest_integrity_ok(all_new_manifests)

    # Build retry order for remaining blockers.
    remaining_union: dict[str, dict[str, Any]] = {}
    retry_rank_hint = {
        str(row.get("expected_input", "")).strip(): safe_int(row.get("retry_rank"))
        for row in retry_order_r48e
        if str(row.get("expected_input", "")).strip()
    }

    for row in manual_still_required_r48f:
        expected_input = str(row.get("expected_input", "")).strip()
        if not expected_input:
            continue
        remaining_union.setdefault(
            expected_input,
            {
                "expected_input": expected_input,
                "priority": safe_int(row.get("priority")),
                "source_family": row.get("source_family", ""),
                "next_action": "require_manual_file",
                "reason": row.get("failure_reason", ""),
            },
        )
    for row in endpoint_remaining_r48f:
        expected_input = str(row.get("expected_input", "")).strip()
        if not expected_input:
            continue
        remaining_union.setdefault(
            expected_input,
            {
                "expected_input": expected_input,
                "priority": safe_int(row.get("priority")),
                "source_family": row.get("source_family", ""),
                "next_action": row.get("next_action", "endpoint_followup"),
                "reason": row.get("failure_reason", ""),
            },
        )
    for row in producer_remaining_r48f:
        expected_input = str(row.get("expected_input", "")).strip()
        if not expected_input:
            continue
        remaining_union.setdefault(
            expected_input,
            {
                "expected_input": expected_input,
                "priority": safe_int(row.get("priority")),
                "source_family": row.get("source_family", ""),
                "next_action": row.get("next_action", "producer_followup"),
                "reason": row.get("failure_reason", ""),
            },
        )

    retry_order_r48f: list[dict[str, Any]] = []
    for expected_input, row in sorted(
        remaining_union.items(),
        key=lambda item: (
            safe_int(item[1].get("priority")),
            retry_rank_hint.get(item[0], 0),
            item[0],
        ),
    ):
        retry_order_r48f.append(
            {
                "retry_rank": len(retry_order_r48f) + 1,
                "priority": safe_int(row.get("priority")),
                "expected_input": expected_input,
                "source_family": str(row.get("source_family", "")),
                "next_action": str(row.get("next_action", "")),
                "reason": str(row.get("reason", "")),
            }
        )

    status_payload = {
        "generated_at": utc_now(),
        "r4_8f_phase_type": "MANUAL_IMPORT_DROPZONE_EXECUTION_AND_ENDPOINT_PATCH_RETRY",
        "r4_8f_gate_passed": False,
        "r4_8f_manual_sources_checked": manual_sources_checked,
        "r4_8f_manual_files_found": manual_files_found,
        "r4_8f_manual_files_validated": manual_files_validated,
        "r4_8f_manual_files_still_required": manual_files_still_required,
        "r4_8f_endpoint_followups_reviewed": endpoint_followups_reviewed,
        "r4_8f_endpoint_patches_applied": endpoint_patches_applied,
        "r4_8f_endpoint_retries_attempted": endpoint_retries_attempted,
        "r4_8f_endpoint_retries_successful": endpoint_retries_successful,
        "r4_8f_producer_patches_applied": producer_patches_applied,
        "r4_8f_producer_retries_attempted": producer_retries_attempted,
        "r4_8f_producer_retries_successful": producer_retries_successful,
        "r4_8f_rows_ingested_total": total_rows_ingested,
        "r4_8f_production_inputs_staged_total": total_staged,
        "r4_8f_validated_source_manifests_total": total_manifests,
        "r4_8f_new_rows_ingested": new_rows_ingested,
        "r4_8f_new_production_inputs_staged": new_staged,
        "r4_8f_new_validated_source_manifests": new_new_manifests,
        "r4_8f_forbidden_artifact_usage": forbidden_artifact_usage,
        "r4_8f_downloads_executed": bool(endpoint_retries_attempted or producer_retries_attempted),
        "row_fabrication_policy": row_fabrication_policy,
        "phase_7_8_blocked": phase_7_8_blocked,
        "inputs": {
            "manual_fallback_package_r4_8e": "data/exports/manual_fallback_package_r4_8e.json",
            "manual_fallback_inventory_r4_8e": "data/exports/manual_fallback_inventory_r4_8e.csv",
            "endpoint_resolution_report_r4_8e": "data/exports/endpoint_resolution_report_r4_8e.csv",
            "producer_failure_resolution_report_r4_8e": "data/exports/producer_failure_resolution_report_r4_8e.csv",
            "manual_files_required_r4_8e": "data/review_queue/manual_files_required_r4_8e.csv",
            "endpoint_followup_required_r4_8e": "data/review_queue/endpoint_followup_required_r4_8e.csv",
            "producer_patch_remaining_r4_8e": "data/review_queue/producer_patch_remaining_r4_8e.csv",
            "backfill_retry_order_r4_8e": "data/review_queue/backfill_retry_order_r4_8e.csv",
            "validated_source_manifest_inventory_r4_8d": "data/exports/validated_source_manifest_inventory_r4_8d.csv",
            "targeted_backfill_retry_status_r4_8d": "data/exports/targeted_backfill_retry_status_r4_8d.json",
        },
        "outputs": {
            "manual_import_dropzone_status_r4_8f": "data/exports/manual_import_dropzone_status_r4_8f.json",
            "manual_import_dropzone_inventory_r4_8f": "data/exports/manual_import_dropzone_inventory_r4_8f.csv",
            "endpoint_patch_retry_report_r4_8f": "data/exports/endpoint_patch_retry_report_r4_8f.csv",
            "producer_patch_retry_report_r4_8f": "data/exports/producer_patch_retry_report_r4_8f.csv",
            "validated_source_manifest_inventory_r4_8f": "data/exports/validated_source_manifest_inventory_r4_8f.csv",
            "manual_files_still_required_r4_8f": "data/review_queue/manual_files_still_required_r4_8f.csv",
            "endpoint_failures_remaining_r4_8f": "data/review_queue/endpoint_failures_remaining_r4_8f.csv",
            "producer_failures_remaining_r4_8f": "data/review_queue/producer_failures_remaining_r4_8f.csv",
            "backfill_retry_order_r4_8f": "data/review_queue/backfill_retry_order_r4_8f.csv",
        },
    }

    gate_passed = (
        all_manual_checked
        and manual_found_accounted
        and manual_required_queued
        and endpoint_classified
        and producer_classified
        and manifest_integrity_ok
        and not forbidden_artifact_usage
        and row_fabrication_policy == "FORBIDDEN_NO_SYNTHETIC_ROWS"
        and phase_7_8_blocked
    )
    status_payload["r4_8f_gate_passed"] = bool(gate_passed)

    write_json(exports_dir / "manual_import_dropzone_status_r4_8f.json", status_payload)
    write_csv(
        exports_dir / "manual_import_dropzone_inventory_r4_8f.csv",
        manual_inventory_r48f,
        [
            "priority",
            "source_family",
            "expected_input",
            "target_dropzone_path",
            "target_output_path",
            "accepted_filename_patterns",
            "required_columns",
            "manual_file_found",
            "manual_file_validated",
            "selected_dropzone_file",
            "selected_dropzone_sha256",
            "selected_dropzone_rows",
            "staged_output_sha256",
            "staged_output_rows",
            "manifest_written",
            "review_status",
            "failure_reason",
            "validation_command",
            "source_url_or_portal",
            "producer_script",
            "forbidden_artifact_usage",
        ],
    )
    write_csv(
        exports_dir / "endpoint_patch_retry_report_r4_8f.csv",
        endpoint_report_r48f,
        [
            "priority",
            "expected_input",
            "source_family",
            "producer_script",
            "endpoint_classification",
            "next_action",
            "source_url_or_portal",
            "target_output_path",
            "deterministic_patch_applied",
            "retry_attempted",
            "retry_status",
            "retry_command",
            "command_exit_code",
            "command_excerpt_safe",
            "row_count",
            "sha256",
            "manifest_written",
            "failure_reason",
        ],
    )
    write_csv(
        exports_dir / "producer_patch_retry_report_r4_8f.csv",
        producer_report_r48f,
        [
            "priority",
            "expected_input",
            "source_family",
            "producer_script",
            "producer_classification",
            "next_action",
            "target_output_path",
            "deterministic_patch_applied",
            "retry_attempted",
            "retry_status",
            "retry_command",
            "command_exit_code",
            "command_excerpt_safe",
            "row_count",
            "sha256",
            "manifest_written",
            "failure_reason",
        ],
    )
    write_csv(
        exports_dir / "validated_source_manifest_inventory_r4_8f.csv",
        manifests_r48f,
        [
            "source_system",
            "source_file",
            "target_output_path",
            "row_count",
            "sha256",
            "generated_at",
            "producer_script",
            "validation_status",
            "known_gaps",
            "schema_version",
            "manifest_type",
            "manifest_path",
        ],
    )
    write_csv(
        review_dir / "manual_files_still_required_r4_8f.csv",
        manual_still_required_r48f,
        [
            "priority",
            "source_family",
            "expected_input",
            "target_dropzone_path",
            "target_output_path",
            "accepted_filename_patterns",
            "required_columns",
            "validation_command",
            "source_url_or_portal",
            "producer_script",
            "manual_file_received",
            "review_status",
            "failure_reason",
        ],
    )
    write_csv(
        review_dir / "endpoint_failures_remaining_r4_8f.csv",
        endpoint_remaining_r48f,
        [
            "priority",
            "expected_input",
            "source_family",
            "producer_script",
            "endpoint_classification",
            "next_action",
            "target_output_path",
            "retry_status",
            "failure_reason",
            "review_status",
        ],
    )
    write_csv(
        review_dir / "producer_failures_remaining_r4_8f.csv",
        producer_remaining_r48f,
        [
            "priority",
            "expected_input",
            "source_family",
            "producer_script",
            "producer_classification",
            "next_action",
            "target_output_path",
            "retry_status",
            "failure_reason",
            "review_status",
        ],
    )
    write_csv(
        review_dir / "backfill_retry_order_r4_8f.csv",
        retry_order_r48f,
        [
            "retry_rank",
            "priority",
            "expected_input",
            "source_family",
            "next_action",
            "reason",
        ],
    )

    rebuild_status.update(
        {
            "r4_8f_generated_at": status_payload["generated_at"],
            "r4_8f_phase_type": status_payload["r4_8f_phase_type"],
            "r4_8f_gate_passed": status_payload["r4_8f_gate_passed"],
            "r4_8f_manual_sources_checked": manual_sources_checked,
            "r4_8f_manual_files_found": manual_files_found,
            "r4_8f_manual_files_validated": manual_files_validated,
            "r4_8f_manual_files_still_required": manual_files_still_required,
            "r4_8f_endpoint_followups_reviewed": endpoint_followups_reviewed,
            "r4_8f_endpoint_patches_applied": endpoint_patches_applied,
            "r4_8f_endpoint_retries_attempted": endpoint_retries_attempted,
            "r4_8f_endpoint_retries_successful": endpoint_retries_successful,
            "r4_8f_producer_patches_applied": producer_patches_applied,
            "r4_8f_producer_retries_attempted": producer_retries_attempted,
            "r4_8f_producer_retries_successful": producer_retries_successful,
            "r4_8f_rows_ingested_total": total_rows_ingested,
            "r4_8f_production_inputs_staged_total": total_staged,
            "r4_8f_validated_source_manifests_total": total_manifests,
            "r4_8f_new_rows_ingested": new_rows_ingested,
            "r4_8f_new_production_inputs_staged": new_staged,
            "r4_8f_new_validated_source_manifests": new_new_manifests,
            "r4_8f_forbidden_artifact_usage": forbidden_artifact_usage,
            "r4_8f_downloads_executed": status_payload["r4_8f_downloads_executed"],
            "row_fabrication_policy": row_fabrication_policy,
            "phase_7_8_blocked": phase_7_8_blocked,
            "r4_8f_outputs": status_payload["outputs"],
        }
    )
    write_json(exports_dir / "rebuild_status.json", rebuild_status)

    return status_payload


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run R4.8F manual import dropzone execution and endpoint/producer retry logic."
    )
    parser.add_argument("--root", default=".", help="Project root path")
    parser.add_argument(
        "--command-timeout-seconds",
        type=int,
        default=30,
        help="Timeout for each endpoint/producer retry command.",
    )
    args = parser.parse_args()

    status = run_manual_import_dropzone_retry(
        Path(args.root),
        command_timeout_seconds=max(1, int(args.command_timeout_seconds)),
    )

    print(f"r4_8f_gate_passed: {status.get('r4_8f_gate_passed')}")
    print(f"r4_8f_manual_sources_checked: {status.get('r4_8f_manual_sources_checked')}")
    print(f"r4_8f_manual_files_found: {status.get('r4_8f_manual_files_found')}")
    print(f"r4_8f_manual_files_validated: {status.get('r4_8f_manual_files_validated')}")
    print(f"r4_8f_manual_files_still_required: {status.get('r4_8f_manual_files_still_required')}")
    print(f"r4_8f_endpoint_followups_reviewed: {status.get('r4_8f_endpoint_followups_reviewed')}")
    print(f"r4_8f_endpoint_patches_applied: {status.get('r4_8f_endpoint_patches_applied')}")
    print(f"r4_8f_endpoint_retries_attempted: {status.get('r4_8f_endpoint_retries_attempted')}")
    print(f"r4_8f_endpoint_retries_successful: {status.get('r4_8f_endpoint_retries_successful')}")
    print(f"r4_8f_producer_patches_applied: {status.get('r4_8f_producer_patches_applied')}")
    print(f"r4_8f_producer_retries_attempted: {status.get('r4_8f_producer_retries_attempted')}")
    print(f"r4_8f_producer_retries_successful: {status.get('r4_8f_producer_retries_successful')}")
    print(f"r4_8f_rows_ingested_total: {status.get('r4_8f_rows_ingested_total')}")
    print(f"r4_8f_production_inputs_staged_total: {status.get('r4_8f_production_inputs_staged_total')}")
    print(
        "r4_8f_validated_source_manifests_total: "
        f"{status.get('r4_8f_validated_source_manifests_total')}"
    )
    print(f"r4_8f_new_rows_ingested: {status.get('r4_8f_new_rows_ingested')}")
    print(
        "r4_8f_new_production_inputs_staged: "
        f"{status.get('r4_8f_new_production_inputs_staged')}"
    )
    print(
        "r4_8f_new_validated_source_manifests: "
        f"{status.get('r4_8f_new_validated_source_manifests')}"
    )
    print(f"r4_8f_forbidden_artifact_usage: {status.get('r4_8f_forbidden_artifact_usage')}")
    print(f"phase_7_8_blocked: {status.get('phase_7_8_blocked')}")
    print(json.dumps(status, indent=2))

    print("wrote: data/exports/manual_import_dropzone_status_r4_8f.json")
    print("wrote: data/exports/manual_import_dropzone_inventory_r4_8f.csv")
    print("wrote: data/exports/endpoint_patch_retry_report_r4_8f.csv")
    print("wrote: data/exports/producer_patch_retry_report_r4_8f.csv")
    print("wrote: data/exports/validated_source_manifest_inventory_r4_8f.csv")
    print("wrote: data/review_queue/manual_files_still_required_r4_8f.csv")
    print("wrote: data/review_queue/endpoint_failures_remaining_r4_8f.csv")
    print("wrote: data/review_queue/producer_failures_remaining_r4_8f.csv")
    print("wrote: data/review_queue/backfill_retry_order_r4_8f.csv")
    print("wrote: data/exports/rebuild_status.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
