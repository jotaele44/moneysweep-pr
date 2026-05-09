"""Run R4.8G manual acquisition and credential-unblock package generation."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from contract_sweeper.pipeline.acquisition_package import (
    build_acquisition_markdown,
    build_backfill_retry_order_r48g,
    build_manual_acquisition_rows,
    read_csv,
    read_json,
    safe_int,
    utc_now,
    write_csv,
    write_json,
    write_markdown,
)
from contract_sweeper.pipeline.credential_unblock_plan import (
    build_endpoint_and_credential_requests,
    build_producer_patch_requests,
)


def run_acquisition_package(root: Path) -> dict[str, object]:
    root = Path(root)
    exports_dir = root / "data" / "exports"
    review_dir = root / "data" / "review_queue"

    status_r48f = read_json(exports_dir / "manual_import_dropzone_status_r4_8f.json")
    manual_inventory_r48f = read_csv(exports_dir / "manual_import_dropzone_inventory_r4_8f.csv")
    endpoint_retry_report_r48f = read_csv(exports_dir / "endpoint_patch_retry_report_r4_8f.csv")
    producer_retry_report_r48f = read_csv(exports_dir / "producer_patch_retry_report_r4_8f.csv")
    validated_manifest_inventory_r48f = read_csv(exports_dir / "validated_source_manifest_inventory_r4_8f.csv")
    manual_required_r48f = read_csv(review_dir / "manual_files_still_required_r4_8f.csv")
    endpoint_remaining_r48f = read_csv(review_dir / "endpoint_failures_remaining_r4_8f.csv")
    producer_remaining_r48f = read_csv(review_dir / "producer_failures_remaining_r4_8f.csv")
    retry_order_r48f = read_csv(review_dir / "backfill_retry_order_r4_8f.csv")
    rebuild_status = read_json(exports_dir / "rebuild_status.json")

    manual_matrix_rows, manual_request_rows, manual_forbidden = build_manual_acquisition_rows(
        manual_required_r48f
    )
    endpoint_request_rows, credential_plan_rows, credential_request_rows = (
        build_endpoint_and_credential_requests(endpoint_remaining_r48f)
    )
    producer_request_rows = build_producer_patch_requests(producer_remaining_r48f)

    retry_order_r48g = build_backfill_retry_order_r48g(
        retry_order_r48f=retry_order_r48f,
        manual_rows=manual_matrix_rows,
        endpoint_rows=endpoint_request_rows,
        producer_rows=producer_request_rows,
    )

    rows_ingested_total = safe_int(
        status_r48f.get("r4_8f_rows_ingested_total", rebuild_status.get("r4_8f_rows_ingested_total", 0))
    )
    production_inputs_staged_total = safe_int(
        status_r48f.get(
            "r4_8f_production_inputs_staged_total",
            rebuild_status.get("r4_8f_production_inputs_staged_total", 0),
        )
    )
    validated_source_manifests_total = safe_int(
        status_r48f.get(
            "r4_8f_validated_source_manifests_total",
            rebuild_status.get("r4_8f_validated_source_manifests_total", len(validated_manifest_inventory_r48f)),
        )
    )
    row_fabrication_policy = str(
        rebuild_status.get("row_fabrication_policy")
        or status_r48f.get("row_fabrication_policy")
        or "FORBIDDEN_NO_SYNTHETIC_ROWS"
    )
    phase_7_8_blocked = bool(
        rebuild_status.get("phase_7_8_blocked", status_r48f.get("phase_7_8_blocked", True))
    )

    generated_at = utc_now()
    forbidden_artifact_usage = bool(manual_forbidden)
    no_downloads_executed = True
    no_rows_ingested = True
    no_staged_inputs = True

    manual_complete = len(manual_matrix_rows) == len(manual_required_r48f) and all(
        bool(str(row.get("exact_manual_export_steps", "")).strip())
        and bool(str(row.get("target_dropzone_path", "")).strip())
        and bool(str(row.get("accepted_filename_patterns", "")).strip())
        and bool(str(row.get("required_columns", "")).strip())
        and bool(str(row.get("target_output_path", "")).strip())
        and bool(str(row.get("validation_command", "")).strip())
        for row in manual_matrix_rows
    )
    endpoint_complete = len(endpoint_request_rows) == len(endpoint_remaining_r48f) and all(
        bool(str(row.get("endpoint_classification", "")).strip())
        and bool(str(row.get("required_credentials_or_auth_status", "")).strip())
        and bool(str(row.get("recommended_endpoint_action", "")).strip())
        for row in endpoint_request_rows
    )
    producer_complete = len(producer_request_rows) == len(producer_remaining_r48f) and all(
        "patch_safe_now" in row and "manual_source_required" in row for row in producer_request_rows
    )

    gate_passed = (
        manual_complete
        and endpoint_complete
        and producer_complete
        and no_downloads_executed
        and no_rows_ingested
        and no_staged_inputs
        and not forbidden_artifact_usage
        and row_fabrication_policy == "FORBIDDEN_NO_SYNTHETIC_ROWS"
        and phase_7_8_blocked
    )

    package_json = {
        "generated_at": generated_at,
        "r4_8g_phase_type": "MANUAL_FILE_ACQUISITION_AND_CREDENTIALED_ENDPOINT_UNBLOCK_RETRY",
        "r4_8g_gate_passed": gate_passed,
        "r4_8g_manual_file_requests": len(manual_request_rows),
        "r4_8g_credential_requests": len(credential_request_rows),
        "r4_8g_endpoint_resolution_requests": len(endpoint_request_rows),
        "r4_8g_producer_patch_requests": len(producer_request_rows),
        "r4_8g_rows_ingested_total": rows_ingested_total,
        "r4_8g_production_inputs_staged_total": production_inputs_staged_total,
        "r4_8g_validated_source_manifests_total": validated_source_manifests_total,
        "r4_8g_new_rows_ingested": 0,
        "r4_8g_new_production_inputs_staged": 0,
        "r4_8g_new_validated_source_manifests": 0,
        "r4_8g_forbidden_artifact_usage": forbidden_artifact_usage,
        "r4_8g_downloads_executed": False,
        "row_fabrication_policy": row_fabrication_policy,
        "phase_7_8_blocked": phase_7_8_blocked,
        "inputs": {
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
        "outputs": {
            "acquisition_package_json": "data/exports/acquisition_package_r4_8g.json",
            "acquisition_package_md": "data/exports/acquisition_package_r4_8g.md",
            "credential_unblock_plan": "data/exports/credential_unblock_plan_r4_8g.csv",
            "manual_file_acquisition_matrix": "data/exports/manual_file_acquisition_matrix_r4_8g.csv",
            "manual_file_requests": "data/review_queue/manual_file_requests_r4_8g.csv",
            "credential_requests": "data/review_queue/credential_requests_r4_8g.csv",
            "endpoint_resolution_requests": "data/review_queue/endpoint_resolution_requests_r4_8g.csv",
            "producer_patch_requests": "data/review_queue/producer_patch_requests_r4_8g.csv",
            "backfill_retry_order_r4_8g": "data/review_queue/backfill_retry_order_r4_8g.csv",
        },
    }

    markdown = build_acquisition_markdown(
        generated_at=generated_at,
        manual_count=len(manual_request_rows),
        endpoint_count=len(endpoint_request_rows),
        producer_count=len(producer_request_rows),
        credential_count=len(credential_request_rows),
    )

    write_json(exports_dir / "acquisition_package_r4_8g.json", package_json)
    write_markdown(exports_dir / "acquisition_package_r4_8g.md", markdown)
    write_csv(
        exports_dir / "credential_unblock_plan_r4_8g.csv",
        credential_plan_rows,
        [
            "priority",
            "source_family",
            "expected_input",
            "endpoint_classification",
            "source_url_or_portal",
            "producer_script",
            "required_credentials_or_auth_status",
            "recommended_endpoint_action",
            "safe_retry_command_if_available",
            "reason_blocked",
            "credential_request_reason",
        ],
    )
    write_csv(
        exports_dir / "manual_file_acquisition_matrix_r4_8g.csv",
        manual_matrix_rows,
        [
            "priority",
            "source_family",
            "expected_input",
            "source_url_or_portal",
            "exact_manual_export_steps",
            "required_file_type",
            "accepted_filename_patterns",
            "required_columns",
            "target_dropzone_path",
            "target_output_path",
            "validation_command",
            "reason_needed",
        ],
    )
    write_csv(
        review_dir / "manual_file_requests_r4_8g.csv",
        manual_request_rows,
        [
            "priority",
            "source_family",
            "expected_input",
            "source_url_or_portal",
            "exact_manual_export_steps",
            "required_file_type",
            "accepted_filename_patterns",
            "required_columns",
            "target_dropzone_path",
            "target_output_path",
            "validation_command",
            "reason_needed",
            "request_status",
        ],
    )
    write_csv(
        review_dir / "credential_requests_r4_8g.csv",
        credential_request_rows,
        [
            "priority",
            "source_family",
            "expected_input",
            "endpoint_classification",
            "source_url_or_portal",
            "producer_script",
            "required_credentials_or_auth_status",
            "recommended_endpoint_action",
            "safe_retry_command_if_available",
            "reason_blocked",
            "credential_request_reason",
        ],
    )
    write_csv(
        review_dir / "endpoint_resolution_requests_r4_8g.csv",
        endpoint_request_rows,
        [
            "priority",
            "source_family",
            "expected_input",
            "endpoint_classification",
            "source_url_or_portal",
            "producer_script",
            "required_credentials_or_auth_status",
            "recommended_endpoint_action",
            "safe_retry_command_if_available",
            "reason_blocked",
        ],
    )
    write_csv(
        review_dir / "producer_patch_requests_r4_8g.csv",
        producer_request_rows,
        [
            "priority",
            "source_family",
            "expected_input",
            "producer_script",
            "failure_reason",
            "recommended_patch",
            "patch_safe_now",
            "manual_source_required",
        ],
    )
    write_csv(
        review_dir / "backfill_retry_order_r4_8g.csv",
        retry_order_r48g,
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
            "r4_8g_generated_at": generated_at,
            "r4_8g_phase_type": package_json["r4_8g_phase_type"],
            "r4_8g_gate_passed": gate_passed,
            "r4_8g_manual_file_requests": len(manual_request_rows),
            "r4_8g_credential_requests": len(credential_request_rows),
            "r4_8g_endpoint_resolution_requests": len(endpoint_request_rows),
            "r4_8g_producer_patch_requests": len(producer_request_rows),
            "r4_8g_rows_ingested_total": rows_ingested_total,
            "r4_8g_production_inputs_staged_total": production_inputs_staged_total,
            "r4_8g_validated_source_manifests_total": validated_source_manifests_total,
            "r4_8g_new_rows_ingested": 0,
            "r4_8g_new_production_inputs_staged": 0,
            "r4_8g_new_validated_source_manifests": 0,
            "r4_8g_forbidden_artifact_usage": forbidden_artifact_usage,
            "r4_8g_downloads_executed": False,
            "r4_8g_outputs": package_json["outputs"],
            "row_fabrication_policy": row_fabrication_policy,
            "phase_7_8_blocked": phase_7_8_blocked,
        }
    )
    write_json(exports_dir / "rebuild_status.json", rebuild_status)

    return package_json


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run R4.8G acquisition package and credential unblock planning"
    )
    parser.add_argument("--root", default=".", help="Project root")
    args = parser.parse_args()

    status = run_acquisition_package(Path(args.root))
    print(f"r4_8g_gate_passed: {status.get('r4_8g_gate_passed')}")
    print(f"r4_8g_manual_file_requests: {status.get('r4_8g_manual_file_requests')}")
    print(f"r4_8g_credential_requests: {status.get('r4_8g_credential_requests')}")
    print(f"r4_8g_endpoint_resolution_requests: {status.get('r4_8g_endpoint_resolution_requests')}")
    print(f"r4_8g_producer_patch_requests: {status.get('r4_8g_producer_patch_requests')}")
    print(f"r4_8g_rows_ingested_total: {status.get('r4_8g_rows_ingested_total')}")
    print(
        "r4_8g_production_inputs_staged_total: "
        f"{status.get('r4_8g_production_inputs_staged_total')}"
    )
    print(
        "r4_8g_validated_source_manifests_total: "
        f"{status.get('r4_8g_validated_source_manifests_total')}"
    )
    print(f"r4_8g_new_rows_ingested: {status.get('r4_8g_new_rows_ingested')}")
    print(
        "r4_8g_new_production_inputs_staged: "
        f"{status.get('r4_8g_new_production_inputs_staged')}"
    )
    print(
        "r4_8g_new_validated_source_manifests: "
        f"{status.get('r4_8g_new_validated_source_manifests')}"
    )
    print(f"r4_8g_forbidden_artifact_usage: {status.get('r4_8g_forbidden_artifact_usage')}")
    print(f"phase_7_8_blocked: {status.get('phase_7_8_blocked')}")
    print(json.dumps(status, indent=2))

    print("wrote: data/exports/acquisition_package_r4_8g.json")
    print("wrote: data/exports/acquisition_package_r4_8g.md")
    print("wrote: data/exports/credential_unblock_plan_r4_8g.csv")
    print("wrote: data/exports/manual_file_acquisition_matrix_r4_8g.csv")
    print("wrote: data/review_queue/manual_file_requests_r4_8g.csv")
    print("wrote: data/review_queue/credential_requests_r4_8g.csv")
    print("wrote: data/review_queue/endpoint_resolution_requests_r4_8g.csv")
    print("wrote: data/review_queue/producer_patch_requests_r4_8g.csv")
    print("wrote: data/review_queue/backfill_retry_order_r4_8g.csv")
    print("wrote: data/exports/rebuild_status.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
