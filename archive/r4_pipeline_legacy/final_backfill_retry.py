"""R4.8H manual fulfillment + credentialed endpoint/producer retry orchestration."""

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
from contract_sweeper.pipeline.credentialed_endpoint_execution import (
    evaluate_credential_requests,
    run_credentialed_endpoint_retries,
    run_producer_patch_retries,
)
from contract_sweeper.pipeline.manual_fulfillment_execution import run_manual_fulfillment_execution


def _to_bool(raw: Any) -> bool:
    return str(raw).strip().lower() in {"1", "true", "yes", "y"}


def _build_manual_by_input(rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    by_input: dict[str, dict[str, str]] = {}
    for row in rows:
        expected_input = str(row.get("expected_input", "")).strip()
        if not expected_input:
            continue
        by_input[expected_input] = row
    return by_input


def _combine_manifests(
    *,
    existing_rows: list[dict[str, str]],
    new_rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int, int, int]:
    by_target: dict[str, dict[str, Any]] = {}

    for row in existing_rows:
        target = str(row.get("target_output_path", "")).strip()
        if not target:
            continue
        by_target[target] = dict(row)

    unique_new_by_target: dict[str, dict[str, Any]] = {}
    for row in new_rows:
        target = str(row.get("target_output_path", "")).strip()
        if not target:
            continue
        unique_new_by_target[target] = dict(row)
        by_target[target] = dict(row)

    combined_rows = list(by_target.values())
    combined_rows.sort(key=lambda row: str(row.get("target_output_path", "")))

    new_rows_ingested = sum(safe_int(row.get("row_count")) for row in unique_new_by_target.values())
    new_staged = len(unique_new_by_target)
    new_manifests = len(unique_new_by_target)

    return combined_rows, new_rows_ingested, new_staged, new_manifests


def _build_final_results(
    *,
    manual_rows: list[dict[str, Any]],
    endpoint_rows: list[dict[str, Any]],
    producer_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    union: dict[str, dict[str, Any]] = {}

    def _ensure(expected_input: str, source_family: str, priority: int) -> dict[str, Any]:
        row = union.setdefault(
            expected_input,
            {
                "expected_input": expected_input,
                "source_family": source_family,
                "priority": priority,
                "manual_status": "not_applicable",
                "credential_status": "not_checked",
                "endpoint_retry_status": "not_applicable",
                "producer_retry_status": "not_applicable",
                "terminal_status": "pending",
                "next_action": "review",
                "reason": "",
            },
        )
        if not row.get("source_family") and source_family:
            row["source_family"] = source_family
        if safe_int(row.get("priority")) == 0 and priority:
            row["priority"] = priority
        return row

    for row in manual_rows:
        expected_input = str(row.get("expected_input", "")).strip()
        if not expected_input:
            continue
        target = _ensure(
            expected_input,
            str(row.get("source_family", "")).strip(),
            safe_int(row.get("priority")),
        )
        if _to_bool(row.get("manual_file_validated")):
            target["manual_status"] = "validated"
            target["terminal_status"] = "ready"
            target["next_action"] = "none"
        elif _to_bool(row.get("manual_file_found")):
            target["manual_status"] = "rejected"
            target["terminal_status"] = "blocked"
            target["next_action"] = "replace_manual_file"
            target["reason"] = str(row.get("failure_reason", "")).strip()
        else:
            target["manual_status"] = "missing"
            target["terminal_status"] = "blocked"
            target["next_action"] = "provide_manual_file"
            target["reason"] = str(row.get("failure_reason", "")).strip() or "manual file missing"

    for row in endpoint_rows:
        expected_input = str(row.get("expected_input", "")).strip()
        if not expected_input:
            continue
        target = _ensure(
            expected_input,
            str(row.get("source_family", "")).strip(),
            safe_int(row.get("priority")),
        )
        target["credential_status"] = (
            "available" if _to_bool(row.get("credentials_available")) else "missing"
        )
        target["endpoint_retry_status"] = str(row.get("retry_status", "")).strip() or "pending"
        if target["endpoint_retry_status"] == "success":
            target["terminal_status"] = "ready"
            target["next_action"] = "none"
            target["reason"] = ""
        else:
            target["terminal_status"] = "blocked"
            target["next_action"] = "retry_endpoint"
            target["reason"] = str(row.get("failure_reason", "")).strip()

    for row in producer_rows:
        expected_input = str(row.get("expected_input", "")).strip()
        if not expected_input:
            continue
        target = _ensure(
            expected_input,
            str(row.get("source_family", "")).strip(),
            safe_int(row.get("priority")),
        )
        target["producer_retry_status"] = str(row.get("retry_status", "")).strip() or "pending"
        if target["producer_retry_status"] == "success":
            target["terminal_status"] = "ready"
            target["next_action"] = "none"
            target["reason"] = ""
        else:
            target["terminal_status"] = "blocked"
            target["next_action"] = "retry_producer"
            target["reason"] = str(row.get("failure_reason", "")).strip()

    rows = list(union.values())
    rows.sort(key=lambda item: (safe_int(item.get("priority")), item.get("expected_input", "")))
    return rows


def _build_retry_order(
    *,
    manual_still_required: list[dict[str, Any]],
    credentials_still_required: list[dict[str, Any]],
    endpoints_still_blocked: list[dict[str, Any]],
    producers_still_blocked: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    union: dict[str, dict[str, Any]] = {}

    def _setdefault(
        expected_input: str,
        *,
        priority: int,
        source_family: str,
        next_action: str,
        reason: str,
    ) -> None:
        if not expected_input:
            return
        if expected_input in union:
            return
        union[expected_input] = {
            "priority": priority,
            "expected_input": expected_input,
            "source_family": source_family,
            "next_action": next_action,
            "reason": reason,
        }

    for row in manual_still_required:
        _setdefault(
            str(row.get("expected_input", "")).strip(),
            priority=safe_int(row.get("priority")),
            source_family=str(row.get("source_family", "")).strip(),
            next_action="require_manual_file",
            reason=str(row.get("failure_reason", "")).strip() or "manual file missing",
        )

    for row in credentials_still_required:
        _setdefault(
            str(row.get("expected_input", "")).strip(),
            priority=safe_int(row.get("priority")),
            source_family=str(row.get("source_family", "")).strip(),
            next_action="provide_credentials",
            reason=str(row.get("missing_env_vars", "")).strip() or "credentials missing",
        )

    for row in endpoints_still_blocked:
        _setdefault(
            str(row.get("expected_input", "")).strip(),
            priority=safe_int(row.get("priority")),
            source_family=str(row.get("source_family", "")).strip(),
            next_action="retry_endpoint",
            reason=str(row.get("failure_reason", "")).strip() or str(row.get("retry_status", "")).strip(),
        )

    for row in producers_still_blocked:
        _setdefault(
            str(row.get("expected_input", "")).strip(),
            priority=safe_int(row.get("priority")),
            source_family=str(row.get("source_family", "")).strip(),
            next_action="retry_producer",
            reason=str(row.get("failure_reason", "")).strip() or str(row.get("retry_status", "")).strip(),
        )

    out_rows: list[dict[str, Any]] = []
    for expected_input, row in sorted(
        union.items(),
        key=lambda item: (safe_int(item[1].get("priority")), item[0]),
    ):
        out_rows.append(
            {
                "retry_rank": len(out_rows) + 1,
                "priority": safe_int(row.get("priority")),
                "expected_input": expected_input,
                "source_family": str(row.get("source_family", "")),
                "next_action": str(row.get("next_action", "")),
                "reason": str(row.get("reason", "")),
            }
        )

    return out_rows


def _staged_integrity_ok(
    manual_rows: list[dict[str, Any]],
    endpoint_rows: list[dict[str, Any]],
    producer_rows: list[dict[str, Any]],
) -> bool:
    for row in manual_rows:
        if _to_bool(row.get("manual_file_validated")):
            if safe_int(row.get("staged_output_rows")) <= 0:
                return False
            if not str(row.get("staged_output_sha256", "")).strip():
                return False
            if not _to_bool(row.get("manifest_written")):
                return False

    for row in endpoint_rows + producer_rows:
        if str(row.get("retry_status", "")).strip() == "success":
            if safe_int(row.get("row_count")) <= 0:
                return False
            if not str(row.get("sha256", "")).strip():
                return False
            if not _to_bool(row.get("manifest_written")):
                return False

    return True


def run_final_backfill_retry(
    root: Path,
    *,
    command_timeout_seconds: int = 20,
) -> dict[str, Any]:
    root = Path(root)
    exports_dir = root / "data" / "exports"
    review_dir = root / "data" / "review_queue"

    # Required R4.8G inputs
    _ = read_json(exports_dir / "acquisition_package_r4_8g.json")
    _ = (exports_dir / "acquisition_package_r4_8g.md").read_text(encoding="utf-8") if (
        exports_dir / "acquisition_package_r4_8g.md"
    ).exists() else ""
    _ = read_csv(exports_dir / "credential_unblock_plan_r4_8g.csv")
    _ = read_csv(exports_dir / "manual_file_acquisition_matrix_r4_8g.csv")

    manual_request_rows = read_csv(review_dir / "manual_file_requests_r4_8g.csv")
    credential_request_rows = read_csv(review_dir / "credential_requests_r4_8g.csv")
    endpoint_request_rows = read_csv(review_dir / "endpoint_resolution_requests_r4_8g.csv")
    producer_patch_rows = read_csv(review_dir / "producer_patch_requests_r4_8g.csv")
    _ = read_csv(review_dir / "backfill_retry_order_r4_8g.csv")

    existing_manifest_inventory = read_csv(exports_dir / "validated_source_manifest_inventory_r4_8f.csv")
    rebuild_status = read_json(exports_dir / "rebuild_status.json")

    manual_by_input = _build_manual_by_input(manual_request_rows)

    manual_result = run_manual_fulfillment_execution(
        root,
        manual_request_rows=manual_request_rows,
    )

    (
        credential_eval_rows,
        credentials_still_required_rows,
        credential_by_input,
        credentials_available,
        credentials_still_required,
        credential_forbidden,
    ) = evaluate_credential_requests(
        root,
        credential_request_rows=credential_request_rows,
    )

    (
        endpoint_results,
        endpoints_still_blocked,
        endpoint_new_manifests,
        endpoint_metrics,
        endpoint_forbidden,
    ) = run_credentialed_endpoint_retries(
        root,
        endpoint_rows=endpoint_request_rows,
        manual_rows_by_input=manual_by_input,
        credential_eval_by_input=credential_by_input,
        command_timeout_s=max(1, int(command_timeout_seconds)),
    )

    (
        producer_results,
        producers_still_blocked,
        producer_new_manifests,
        producer_metrics,
        producer_forbidden,
    ) = run_producer_patch_retries(
        root,
        producer_rows=producer_patch_rows,
        manual_rows_by_input=manual_by_input,
        command_timeout_s=max(1, int(command_timeout_seconds)),
    )

    manual_new_manifests = list(manual_result.get("manual_new_manifests", []))
    all_new_manifests = manual_new_manifests + endpoint_new_manifests + producer_new_manifests

    combined_manifest_inventory, new_rows_ingested, new_staged, new_manifests = _combine_manifests(
        existing_rows=existing_manifest_inventory,
        new_rows=all_new_manifests,
    )

    base_rows_ingested = safe_int(
        rebuild_status.get("r4_8g_rows_ingested_total", rebuild_status.get("r4_8f_rows_ingested_total", 0))
    )
    base_staged = safe_int(
        rebuild_status.get(
            "r4_8g_production_inputs_staged_total",
            rebuild_status.get("r4_8f_production_inputs_staged_total", 0),
        )
    )
    base_manifests = safe_int(
        rebuild_status.get(
            "r4_8g_validated_source_manifests_total",
            rebuild_status.get("r4_8f_validated_source_manifests_total", len(existing_manifest_inventory)),
        )
    )

    rows_ingested_total = base_rows_ingested + new_rows_ingested
    production_inputs_staged_total = base_staged + new_staged
    validated_source_manifests_total = base_manifests + new_manifests

    row_fabrication_policy = str(
        rebuild_status.get("row_fabrication_policy") or "FORBIDDEN_NO_SYNTHETIC_ROWS"
    )
    phase_7_8_blocked = bool(rebuild_status.get("phase_7_8_blocked", True))

    forbidden_artifact_usage = bool(
        manual_result.get("manual_forbidden_artifact_usage")
        or credential_forbidden
        or endpoint_forbidden
        or producer_forbidden
    )

    manual_inventory_rows = list(manual_result.get("manual_inventory_rows", []))
    manual_still_required_rows = list(manual_result.get("manual_still_required_rows", []))

    manual_requests_checked = int(manual_result.get("manual_requests_checked", 0))
    manual_files_found = int(manual_result.get("manual_files_found", 0))
    manual_files_validated = int(manual_result.get("manual_files_validated", 0))
    manual_files_still_required = int(manual_result.get("manual_files_still_required", 0))

    credential_requests_checked = len(credential_request_rows)

    endpoint_retries_attempted = int(endpoint_metrics.get("endpoint_retries_attempted", 0))
    endpoint_retries_successful = int(endpoint_metrics.get("endpoint_retries_successful", 0))

    producer_patches_applied = int(producer_metrics.get("producer_patches_applied", 0))
    producer_retries_attempted = int(producer_metrics.get("producer_retries_attempted", 0))
    producer_retries_successful = int(producer_metrics.get("producer_retries_successful", 0))

    final_retry_rows = _build_final_results(
        manual_rows=manual_inventory_rows,
        endpoint_rows=endpoint_results,
        producer_rows=producer_results,
    )
    retry_order_rows = _build_retry_order(
        manual_still_required=manual_still_required_rows,
        credentials_still_required=credentials_still_required_rows,
        endpoints_still_blocked=endpoints_still_blocked,
        producers_still_blocked=producers_still_blocked,
    )

    all_queues_checked = (
        manual_requests_checked == len(manual_request_rows)
        and credential_requests_checked == len(credential_request_rows)
        and len(endpoint_results) == len(endpoint_request_rows)
        and len(producer_results) == len(producer_patch_rows)
    )

    unresolved_manual_queued = manual_files_still_required == len(manual_still_required_rows)
    unresolved_cred_queued = credentials_still_required == len(credentials_still_required_rows)

    endpoint_terminal = all(
        str(row.get("retry_status", "")).strip() not in {"", "pending"}
        for row in endpoint_results
    )
    producer_terminal = all(
        str(row.get("retry_status", "")).strip() not in {"", "pending"}
        for row in producer_results
    )

    staged_integrity_ok = _staged_integrity_ok(
        manual_rows=manual_inventory_rows,
        endpoint_rows=endpoint_results,
        producer_rows=producer_results,
    )

    gate_passed = bool(
        all_queues_checked
        and unresolved_manual_queued
        and unresolved_cred_queued
        and endpoint_terminal
        and producer_terminal
        and staged_integrity_ok
        and not forbidden_artifact_usage
        and row_fabrication_policy == "FORBIDDEN_NO_SYNTHETIC_ROWS"
        and phase_7_8_blocked
    )

    status_payload = {
        "generated_at": utc_now(),
        "r4_8h_phase_type": "MANUAL_FILE_FULFILLMENT_AND_CREDENTIALED_ENDPOINT_EXECUTION_RETRY",
        "r4_8h_gate_passed": gate_passed,
        "r4_8h_manual_requests_checked": manual_requests_checked,
        "r4_8h_manual_files_found": manual_files_found,
        "r4_8h_manual_files_validated": manual_files_validated,
        "r4_8h_manual_files_still_required": manual_files_still_required,
        "r4_8h_credential_requests_checked": credential_requests_checked,
        "r4_8h_credentials_available": credentials_available,
        "r4_8h_credentials_still_required": credentials_still_required,
        "r4_8h_endpoint_retries_attempted": endpoint_retries_attempted,
        "r4_8h_endpoint_retries_successful": endpoint_retries_successful,
        "r4_8h_producer_patches_applied": producer_patches_applied,
        "r4_8h_producer_retries_attempted": producer_retries_attempted,
        "r4_8h_producer_retries_successful": producer_retries_successful,
        "r4_8h_rows_ingested_total": rows_ingested_total,
        "r4_8h_production_inputs_staged_total": production_inputs_staged_total,
        "r4_8h_validated_source_manifests_total": validated_source_manifests_total,
        "r4_8h_new_rows_ingested": new_rows_ingested,
        "r4_8h_new_production_inputs_staged": new_staged,
        "r4_8h_new_validated_source_manifests": new_manifests,
        "r4_8h_forbidden_artifact_usage": forbidden_artifact_usage,
        "row_fabrication_policy": row_fabrication_policy,
        "phase_7_8_blocked": phase_7_8_blocked,
        "inputs": {
            "acquisition_package_r4_8g": "data/exports/acquisition_package_r4_8g.json",
            "credential_unblock_plan_r4_8g": "data/exports/credential_unblock_plan_r4_8g.csv",
            "manual_file_requests_r4_8g": "data/review_queue/manual_file_requests_r4_8g.csv",
            "credential_requests_r4_8g": "data/review_queue/credential_requests_r4_8g.csv",
            "endpoint_resolution_requests_r4_8g": "data/review_queue/endpoint_resolution_requests_r4_8g.csv",
            "producer_patch_requests_r4_8g": "data/review_queue/producer_patch_requests_r4_8g.csv",
            "validated_source_manifest_inventory_r4_8f": "data/exports/validated_source_manifest_inventory_r4_8f.csv",
            "rebuild_status": "data/exports/rebuild_status.json",
        },
        "outputs": {
            "status": "data/exports/manual_fulfillment_endpoint_retry_status_r4_8h.json",
            "manual_results": "data/exports/manual_fulfillment_results_r4_8h.csv",
            "endpoint_results": "data/exports/credentialed_endpoint_retry_results_r4_8h.csv",
            "final_results": "data/exports/final_backfill_retry_results_r4_8h.csv",
            "validated_manifest_inventory": "data/exports/validated_source_manifest_inventory_r4_8h.csv",
            "manual_files_still_required": "data/review_queue/manual_files_still_required_r4_8h.csv",
            "credentials_still_required": "data/review_queue/credentials_still_required_r4_8h.csv",
            "endpoints_still_blocked": "data/review_queue/endpoints_still_blocked_r4_8h.csv",
            "producers_still_blocked": "data/review_queue/producers_still_blocked_r4_8h.csv",
            "backfill_retry_order": "data/review_queue/backfill_retry_order_r4_8h.csv",
        },
    }

    write_json(exports_dir / "manual_fulfillment_endpoint_retry_status_r4_8h.json", status_payload)

    write_csv(
        exports_dir / "manual_fulfillment_results_r4_8h.csv",
        manual_inventory_rows,
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
        exports_dir / "credentialed_endpoint_retry_results_r4_8h.csv",
        endpoint_results,
        [
            "priority",
            "expected_input",
            "source_family",
            "producer_script",
            "endpoint_classification",
            "recommended_endpoint_action",
            "target_output_path",
            "required_env_vars",
            "missing_env_vars",
            "credentials_available",
            "retry_attempted",
            "retry_status",
            "retry_command",
            "command_exit_code",
            "command_excerpt_safe",
            "row_count",
            "sha256",
            "manifest_written",
            "validation_status",
            "failure_reason",
        ],
    )

    write_csv(
        exports_dir / "final_backfill_retry_results_r4_8h.csv",
        final_retry_rows,
        [
            "priority",
            "expected_input",
            "source_family",
            "manual_status",
            "credential_status",
            "endpoint_retry_status",
            "producer_retry_status",
            "terminal_status",
            "next_action",
            "reason",
        ],
    )

    write_csv(
        exports_dir / "validated_source_manifest_inventory_r4_8h.csv",
        combined_manifest_inventory,
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
        review_dir / "manual_files_still_required_r4_8h.csv",
        manual_still_required_rows,
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
        review_dir / "credentials_still_required_r4_8h.csv",
        credentials_still_required_rows,
        [
            "priority",
            "source_family",
            "expected_input",
            "endpoint_classification",
            "source_url_or_portal",
            "producer_script",
            "required_credentials_or_auth_status",
            "required_env_vars",
            "missing_env_vars",
            "credentials_available",
            "reason_blocked",
            "credential_check_status",
            "review_status",
        ],
    )

    write_csv(
        review_dir / "endpoints_still_blocked_r4_8h.csv",
        endpoints_still_blocked,
        [
            "priority",
            "expected_input",
            "source_family",
            "producer_script",
            "endpoint_classification",
            "recommended_endpoint_action",
            "target_output_path",
            "required_env_vars",
            "missing_env_vars",
            "credentials_available",
            "retry_attempted",
            "retry_status",
            "retry_command",
            "command_exit_code",
            "command_excerpt_safe",
            "row_count",
            "sha256",
            "manifest_written",
            "validation_status",
            "failure_reason",
            "review_status",
        ],
    )

    write_csv(
        review_dir / "producers_still_blocked_r4_8h.csv",
        producers_still_blocked,
        [
            "priority",
            "expected_input",
            "source_family",
            "producer_script",
            "target_output_path",
            "patch_safe_now",
            "manual_source_required",
            "deterministic_patch_applied",
            "required_env_vars",
            "missing_env_vars",
            "retry_attempted",
            "retry_status",
            "retry_command",
            "command_exit_code",
            "command_excerpt_safe",
            "row_count",
            "sha256",
            "manifest_written",
            "validation_status",
            "failure_reason",
            "review_status",
        ],
    )

    write_csv(
        review_dir / "backfill_retry_order_r4_8h.csv",
        retry_order_rows,
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
            "r4_8h_generated_at": status_payload["generated_at"],
            "r4_8h_phase_type": status_payload["r4_8h_phase_type"],
            "r4_8h_gate_passed": gate_passed,
            "r4_8h_manual_requests_checked": manual_requests_checked,
            "r4_8h_manual_files_found": manual_files_found,
            "r4_8h_manual_files_validated": manual_files_validated,
            "r4_8h_manual_files_still_required": manual_files_still_required,
            "r4_8h_credential_requests_checked": credential_requests_checked,
            "r4_8h_credentials_available": credentials_available,
            "r4_8h_credentials_still_required": credentials_still_required,
            "r4_8h_endpoint_retries_attempted": endpoint_retries_attempted,
            "r4_8h_endpoint_retries_successful": endpoint_retries_successful,
            "r4_8h_producer_patches_applied": producer_patches_applied,
            "r4_8h_producer_retries_attempted": producer_retries_attempted,
            "r4_8h_producer_retries_successful": producer_retries_successful,
            "r4_8h_rows_ingested_total": rows_ingested_total,
            "r4_8h_production_inputs_staged_total": production_inputs_staged_total,
            "r4_8h_validated_source_manifests_total": validated_source_manifests_total,
            "r4_8h_new_rows_ingested": new_rows_ingested,
            "r4_8h_new_production_inputs_staged": new_staged,
            "r4_8h_new_validated_source_manifests": new_manifests,
            "r4_8h_forbidden_artifact_usage": forbidden_artifact_usage,
            "row_fabrication_policy": row_fabrication_policy,
            "phase_7_8_blocked": phase_7_8_blocked,
            "r4_8h_outputs": status_payload["outputs"],
        }
    )
    write_json(exports_dir / "rebuild_status.json", rebuild_status)

    return status_payload
