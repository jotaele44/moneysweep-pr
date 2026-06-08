"""R4.9C external validated source delivery and materialization gate."""

from __future__ import annotations

import json
import shutil
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
from contract_sweeper.pipeline.delivered_source_validation import (
    contains_forbidden_token,
    discover_candidate_paths,
    relative_posix,
    resolve_abs,
    row_count,
    sha256,
    validate_candidate,
)

VALIDATED_MANIFEST_TYPE = "validated_source_manifest"
MANIFEST_SCHEMA_VERSION = "r4_9c_schema_v1"
DEFAULT_REQUIRED_COLUMNS = (
    "award_id|recipient_name|recipient_name_normalized|recipient_uei|awarding_agency|"
    "awarding_sub_agency|obligated_amount|award_date|fiscal_year|pop_state|pop_county|"
    "description|source_file|source_dataset|award_category|source_system|source_record_id|"
    "source_lineage_path|source_lineage_mode"
)


def _status_is_validated(value: str) -> bool:
    lowered = str(value or "").strip().lower()
    if not lowered:
        return False
    if lowered.startswith("valid"):
        return True
    return lowered in {"ok", "passed", "success", VALIDATED_MANIFEST_TYPE}


def _manifest_relpath(expected_input: str) -> str:
    stem = Path(expected_input).stem or "source"
    safe = "".join(ch if ch.isalnum() else "_" for ch in stem).strip("_") or "source"
    return f"data/manifests/r4_9c/{safe}.manifest.json"


def _build_validated_requests(
    manifest_rows: list[dict[str, str]],
) -> list[dict[str, Any]]:
    requests: list[dict[str, Any]] = []
    for idx, row in enumerate(manifest_rows, start=1):
        expected_input = str(row.get("target_output_path", "")).strip()
        source_file = str(row.get("source_file", "")).strip()
        manifest_path = str(row.get("manifest_path", "")).strip()

        requests.append(
            {
                "request_id": f"validated:{expected_input or idx}",
                "request_type": "validated_manifest_delivery",
                "priority": idx,
                "source_family": str(row.get("source_system", "")).strip() or "validated_manifest",
                "expected_input": expected_input,
                "target_output_path": expected_input,
                "source_file": source_file,
                "manifest_path": manifest_path,
                "target_dropzone_path": "",
                "accepted_filename_patterns": f"{Path(expected_input).name}|{Path(source_file).name}",
                "required_columns": DEFAULT_REQUIRED_COLUMNS,
                "expected_row_count": safe_int(row.get("row_count")),
                "expected_sha256": str(row.get("sha256", "")).strip(),
                "validation_status": str(row.get("validation_status", "")).strip(),
                "manifest_type": str(row.get("manifest_type", "")).strip(),
                "known_gaps": str(row.get("known_gaps", "")).strip(),
                "producer_script": str(row.get("producer_script", "")).strip(),
                "source_url_or_portal": "",
                "is_manual_request": False,
            }
        )
    return requests


def _build_manual_requests(
    manual_rows: list[dict[str, str]],
    manifest_by_target: dict[str, dict[str, str]],
) -> list[dict[str, Any]]:
    requests: list[dict[str, Any]] = []
    for row in manual_rows:
        expected_input = str(row.get("expected_input", "")).strip()
        target_output_path = str(row.get("target_output_path", "")).strip() or expected_input
        manifest_row = manifest_by_target.get(target_output_path, {})

        requests.append(
            {
                "request_id": f"manual:{expected_input}",
                "request_type": "manual_file_delivery",
                "priority": safe_int(row.get("priority")),
                "source_family": str(row.get("source_family", "")).strip(),
                "expected_input": expected_input,
                "target_output_path": target_output_path,
                "source_file": str(row.get("source_file", "")).strip() or target_output_path,
                "manifest_path": str(manifest_row.get("manifest_path", "")).strip(),
                "target_dropzone_path": str(row.get("target_dropzone_path", "")).strip(),
                "accepted_filename_patterns": str(row.get("accepted_filename_patterns", "")).strip(),
                "required_columns": str(row.get("required_columns", "")).strip(),
                "expected_row_count": safe_int(manifest_row.get("row_count")),
                "expected_sha256": str(manifest_row.get("sha256", "")).strip(),
                "validation_status": str(manifest_row.get("validation_status", "")).strip(),
                "manifest_type": str(manifest_row.get("manifest_type", "")).strip(),
                "known_gaps": str(manifest_row.get("known_gaps", "")).strip(),
                "producer_script": str(manifest_row.get("producer_script", "")).strip(),
                "source_url_or_portal": str(row.get("source_url_or_portal", "")).strip(),
                "is_manual_request": True,
            }
        )
    return requests


def _write_manifest(
    root: Path,
    *,
    request: dict[str, Any],
    target_abs: Path,
    resolved_source_path: str,
) -> dict[str, str]:
    target_output_path = str(request.get("target_output_path", "")).strip()
    row_cnt = row_count(target_abs)
    file_sha = sha256(target_abs)
    manifest_rel = _manifest_relpath(target_output_path or str(request.get("expected_input", "")))
    manifest_abs = root / manifest_rel

    payload = {
        "source_system": str(request.get("source_family", "")).strip(),
        "source_file": resolved_source_path,
        "target_output_path": target_output_path,
        "row_count": row_cnt,
        "sha256": file_sha,
        "generated_at": utc_now(),
        "producer_script": "scripts/run_external_source_delivery_gate_r49c.py",
        "validation_status": "validated",
        "known_gaps": str(request.get("known_gaps", "")).strip(),
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "manifest_type": VALIDATED_MANIFEST_TYPE,
        "manifest_path": manifest_rel,
    }
    manifest_abs.parent.mkdir(parents=True, exist_ok=True)
    manifest_abs.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return payload


def run_external_source_delivery_gate(root: Path) -> dict[str, Any]:
    root = Path(root)
    exports_dir = root / "data" / "exports"
    review_dir = root / "data" / "review_queue"

    _ = read_json(exports_dir / "source_materialization_status_r4_9b.json")
    _ = read_csv(exports_dir / "source_materialization_results_r4_9b.csv")
    _ = read_json(exports_dir / "partial_rebuild_retry_status_r4_9b.json")
    _ = read_csv(exports_dir / "partial_rebuild_retry_inputs_r4_9b.csv")
    _ = read_csv(review_dir / "source_materialization_blockers_r4_9b.csv")
    _ = read_csv(review_dir / "partial_rebuild_retry_blockers_r4_9b.csv")
    external_blockers = read_json(exports_dir / "external_acquisition_blocker_package_r4_8i.json")

    manifest_rows = read_csv(exports_dir / "validated_source_manifest_inventory_r4_8i.csv")
    manual_rows = read_csv(review_dir / "manual_files_still_required_r4_8i.csv")
    rebuild_status = read_json(exports_dir / "rebuild_status.json")

    manifest_by_target = {
        str(row.get("target_output_path", "")).strip(): row
        for row in manifest_rows
        if str(row.get("target_output_path", "")).strip()
    }
    requests = _build_validated_requests(manifest_rows) + _build_manual_requests(manual_rows, manifest_by_target)
    requests = sorted(requests, key=lambda row: (safe_int(row.get("priority")), str(row.get("request_id", ""))))

    results_rows: list[dict[str, Any]] = []
    validation_rows: list[dict[str, Any]] = []
    blocker_rows: list[dict[str, Any]] = []
    manual_still_required_rows: list[dict[str, Any]] = []
    physical_missing_rows: list[dict[str, Any]] = []
    retry_order_rows: list[dict[str, Any]] = []
    new_manifest_rows: list[dict[str, str]] = []

    forbidden_artifact_usage = False
    files_found = 0
    files_validated = 0
    files_materialized = 0
    new_rows_available = 0

    for request in requests:
        request_id = str(request.get("request_id", "")).strip()
        expected_input = str(request.get("expected_input", "")).strip()
        request_type = str(request.get("request_type", "")).strip()
        target_output_path = str(request.get("target_output_path", "")).strip()
        expected_sha = str(request.get("expected_sha256", "")).strip()
        required_columns = str(request.get("required_columns", "")).strip()
        accepted_patterns = str(request.get("accepted_filename_patterns", "")).strip()

        validation_status = str(request.get("validation_status", "")).strip()
        manifest_type = str(request.get("manifest_type", "")).strip()
        if request_type == "validated_manifest_delivery" and (
            not _status_is_validated(validation_status) or manifest_type.lower() != VALIDATED_MANIFEST_TYPE
        ):
            blocker_reason = "invalid_validated_manifest_metadata"
            blocker_rows.append(
                {
                    "request_id": request_id,
                    "request_type": request_type,
                    "source_family": str(request.get("source_family", "")).strip(),
                    "expected_input": expected_input,
                    "target_output_path": target_output_path,
                    "blocker_reason": blocker_reason,
                    "next_action": "fix_manifest_metadata",
                }
            )
            physical_missing_rows.append(
                {
                    "request_id": request_id,
                    "source_family": str(request.get("source_family", "")).strip(),
                    "expected_input": expected_input,
                    "target_output_path": target_output_path,
                    "failure_reason": blocker_reason,
                    "review_status": "pending_manifest_fix",
                }
            )
            retry_order_rows.append(
                {
                    "retry_rank": len(retry_order_rows) + 1,
                    "priority": safe_int(request.get("priority")),
                    "expected_input": expected_input,
                    "source_family": str(request.get("source_family", "")).strip(),
                    "next_action": "fix_manifest_metadata",
                    "reason": blocker_reason,
                }
            )
            results_rows.append(
                {
                    "request_id": request_id,
                    "request_type": request_type,
                    "source_family": str(request.get("source_family", "")).strip(),
                    "expected_input": expected_input,
                    "target_output_path": target_output_path,
                    "files_found": 0,
                    "delivery_status": "blocked",
                    "validation_result": "failed",
                    "materialized": False,
                    "row_count": 0,
                    "sha256": "",
                    "resolved_source_path": "",
                    "blocker_reason": blocker_reason,
                }
            )
            continue

        candidates = discover_candidate_paths(root, request)
        terminal_status = "absent"
        terminal_reason = "file_not_delivered"
        resolved_source_path = ""
        materialized = False
        validated = False
        materialized_rows = 0
        materialized_sha = ""

        if candidates:
            files_found += 1

        for candidate in candidates:
            candidate_valid, details, fail_reason = validate_candidate(
                root=root,
                candidate=candidate,
                expected_sha256=expected_sha,
                accepted_filename_patterns=accepted_patterns if request.get("is_manual_request") else "",
                required_columns=required_columns,
            )
            validation_rows.append(
                {
                    "request_id": request_id,
                    "request_type": request_type,
                    "expected_input": expected_input,
                    "candidate_path": str(candidate),
                    "candidate_relpath": relative_posix(root, candidate),
                    "candidate_found": True,
                    "candidate_valid": candidate_valid,
                    "validation_reason": fail_reason if not candidate_valid else "validated",
                    "candidate_row_count": safe_int(details.get("candidate_row_count")),
                    "candidate_sha256": str(details.get("candidate_sha256", "")).strip(),
                    "missing_columns": str(details.get("missing_columns", "")).strip(),
                }
            )
            if not candidate_valid:
                terminal_status = "found_but_invalid"
                terminal_reason = fail_reason
                continue

            target_abs = resolve_abs(root, target_output_path)
            if contains_forbidden_token(str(target_abs)):
                forbidden_artifact_usage = True
                terminal_status = "blocked_forbidden"
                terminal_reason = "target_path_forbidden_artifact"
                break

            target_abs.parent.mkdir(parents=True, exist_ok=True)
            if candidate.resolve() != target_abs.resolve():
                shutil.copy2(candidate, target_abs)

            post_rows = row_count(target_abs)
            post_sha = sha256(target_abs)
            if post_rows <= 0:
                terminal_status = "found_but_invalid"
                terminal_reason = "materialized_output_empty"
                continue
            if expected_sha and post_sha.lower() != expected_sha.lower():
                terminal_status = "found_but_invalid"
                terminal_reason = "materialized_output_hash_mismatch"
                continue

            resolved_source_path = relative_posix(root, candidate) or str(candidate)
            manifest_row = _write_manifest(
                root,
                request=request,
                target_abs=target_abs,
                resolved_source_path=resolved_source_path,
            )
            new_manifest_rows.append(manifest_row)
            validated = True
            materialized = True
            files_validated += 1
            files_materialized += 1
            materialized_rows = safe_int(manifest_row.get("row_count"))
            materialized_sha = str(manifest_row.get("sha256", "")).strip()
            new_rows_available += materialized_rows
            terminal_status = "validated_and_materialized"
            terminal_reason = ""
            break

        if not validated:
            reason = terminal_reason or "file_not_delivered"
            blocker_rows.append(
                {
                    "request_id": request_id,
                    "request_type": request_type,
                    "source_family": str(request.get("source_family", "")).strip(),
                    "expected_input": expected_input,
                    "target_output_path": target_output_path,
                    "blocker_reason": reason,
                    "next_action": (
                        "manual_source_delivery"
                        if request.get("is_manual_request")
                        else "physical_validated_source_delivery"
                    ),
                }
            )
            retry_order_rows.append(
                {
                    "retry_rank": len(retry_order_rows) + 1,
                    "priority": safe_int(request.get("priority")),
                    "expected_input": expected_input,
                    "source_family": str(request.get("source_family", "")).strip(),
                    "next_action": (
                        "manual_source_delivery"
                        if request.get("is_manual_request")
                        else "physical_validated_source_delivery"
                    ),
                    "reason": reason,
                }
            )
            if request.get("is_manual_request"):
                manual_still_required_rows.append(
                    {
                        "priority": safe_int(request.get("priority")),
                        "source_family": str(request.get("source_family", "")).strip(),
                        "expected_input": expected_input,
                        "target_dropzone_path": str(request.get("target_dropzone_path", "")).strip(),
                        "target_output_path": target_output_path,
                        "accepted_filename_patterns": accepted_patterns,
                        "required_columns": required_columns,
                        "source_url_or_portal": str(request.get("source_url_or_portal", "")).strip(),
                        "failure_reason": reason,
                        "review_status": "pending_manual_file",
                    }
                )
            else:
                physical_missing_rows.append(
                    {
                        "request_id": request_id,
                        "source_family": str(request.get("source_family", "")).strip(),
                        "expected_input": expected_input,
                        "target_output_path": target_output_path,
                        "manifest_path": str(request.get("manifest_path", "")).strip(),
                        "failure_reason": reason,
                        "review_status": "pending_physical_delivery",
                    }
                )

        results_rows.append(
            {
                "request_id": request_id,
                "request_type": request_type,
                "source_family": str(request.get("source_family", "")).strip(),
                "expected_input": expected_input,
                "target_output_path": target_output_path,
                "files_found": 1 if candidates else 0,
                "delivery_status": terminal_status,
                "validation_result": "passed" if validated else "failed_or_absent",
                "materialized": materialized,
                "row_count": materialized_rows,
                "sha256": materialized_sha,
                "resolved_source_path": resolved_source_path,
                "blocker_reason": terminal_reason,
            }
        )

    # Build merged validated manifest inventory (R4.8I baseline + R4.9C updates)
    inventory_by_target: dict[str, dict[str, str]] = {}
    for row in manifest_rows:
        target = str(row.get("target_output_path", "")).strip()
        if target:
            inventory_by_target[target] = dict(row)
    for row in new_manifest_rows:
        target = str(row.get("target_output_path", "")).strip()
        if target:
            inventory_by_target[target] = dict(row)
    merged_inventory_rows = sorted(inventory_by_target.values(), key=lambda row: str(row.get("target_output_path", "")))
    validated_source_manifests_total = len(merged_inventory_rows)
    new_validated_source_manifests = len(new_manifest_rows)
    rows_available_total = sum(safe_int(row.get("row_count")) for row in merged_inventory_rows)

    delivery_requests_checked = len(requests)
    delivery_blockers = len(blocker_rows)
    manual_files_still_required = len(manual_still_required_rows)
    physical_validated_files_still_missing = len(physical_missing_rows)

    production_status = "NON_PRODUCTION_DIAGNOSTIC"
    row_fabrication_policy = str(
        rebuild_status.get("row_fabrication_policy") or "FORBIDDEN_NO_SYNTHETIC_ROWS"
    )
    phase_7_8_blocked = bool(rebuild_status.get("phase_7_8_blocked", True))

    all_checked = delivery_requests_checked == len(results_rows)
    found_validated_or_rejected = all(
        (safe_int(row.get("files_found")) == 0)
        or (str(row.get("validation_result", "")).strip() in {"passed", "failed_or_absent"})
        for row in results_rows
    )
    materialized_manifest_consistent = files_materialized == new_validated_source_manifests

    gate_passed = bool(
        all_checked
        and found_validated_or_rejected
        and materialized_manifest_consistent
        and not forbidden_artifact_usage
        and production_status == "NON_PRODUCTION_DIAGNOSTIC"
        and row_fabrication_policy == "FORBIDDEN_NO_SYNTHETIC_ROWS"
        and phase_7_8_blocked
    )

    status_payload = {
        "generated_at": utc_now(),
        "r4_9c_gate_passed": gate_passed,
        "r4_9c_delivery_requests_checked": delivery_requests_checked,
        "r4_9c_files_found": files_found,
        "r4_9c_files_validated": files_validated,
        "r4_9c_files_materialized": files_materialized,
        "r4_9c_validated_source_manifests_total": validated_source_manifests_total,
        "r4_9c_new_validated_source_manifests": new_validated_source_manifests,
        "r4_9c_rows_available_total": rows_available_total,
        "r4_9c_new_rows_available": new_rows_available,
        "r4_9c_delivery_blockers": delivery_blockers,
        "r4_9c_manual_files_still_required": manual_files_still_required,
        "r4_9c_physical_validated_files_still_missing": physical_validated_files_still_missing,
        "r4_9c_forbidden_artifact_usage": forbidden_artifact_usage,
        "r4_9c_external_blocker_count": safe_int(external_blockers.get("external_blocker_count")),
        "production_status": production_status,
        "row_fabrication_policy": row_fabrication_policy,
        "phase_7_8_blocked": phase_7_8_blocked,
    }

    # Persist outputs
    write_json(exports_dir / "external_source_delivery_status_r4_9c.json", status_payload)
    write_csv(
        exports_dir / "external_source_delivery_results_r4_9c.csv",
        results_rows,
        [
            "request_id",
            "request_type",
            "source_family",
            "expected_input",
            "target_output_path",
            "files_found",
            "delivery_status",
            "validation_result",
            "materialized",
            "row_count",
            "sha256",
            "resolved_source_path",
            "blocker_reason",
        ],
    )
    write_csv(
        exports_dir / "delivered_source_validation_report_r4_9c.csv",
        validation_rows,
        [
            "request_id",
            "request_type",
            "expected_input",
            "candidate_path",
            "candidate_relpath",
            "candidate_found",
            "candidate_valid",
            "validation_reason",
            "candidate_row_count",
            "candidate_sha256",
            "missing_columns",
        ],
    )
    write_csv(
        exports_dir / "validated_source_manifest_inventory_r4_9c.csv",
        merged_inventory_rows,
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
        review_dir / "external_source_delivery_blockers_r4_9c.csv",
        blocker_rows,
        [
            "request_id",
            "request_type",
            "source_family",
            "expected_input",
            "target_output_path",
            "blocker_reason",
            "next_action",
        ],
    )
    write_csv(
        review_dir / "manual_files_still_required_r4_9c.csv",
        manual_still_required_rows,
        [
            "priority",
            "source_family",
            "expected_input",
            "target_dropzone_path",
            "target_output_path",
            "accepted_filename_patterns",
            "required_columns",
            "source_url_or_portal",
            "failure_reason",
            "review_status",
        ],
    )
    write_csv(
        review_dir / "physical_validated_files_still_missing_r4_9c.csv",
        physical_missing_rows,
        [
            "request_id",
            "source_family",
            "expected_input",
            "target_output_path",
            "manifest_path",
            "failure_reason",
            "review_status",
        ],
    )
    write_csv(
        review_dir / "backfill_retry_order_r4_9c.csv",
        retry_order_rows,
        ["retry_rank", "priority", "expected_input", "source_family", "next_action", "reason"],
    )

    rebuild_status.update(
        {
            "r4_9c_generated_at": status_payload["generated_at"],
            "r4_9c_gate_passed": gate_passed,
            "r4_9c_delivery_requests_checked": delivery_requests_checked,
            "r4_9c_files_found": files_found,
            "r4_9c_files_validated": files_validated,
            "r4_9c_files_materialized": files_materialized,
            "r4_9c_validated_source_manifests_total": validated_source_manifests_total,
            "r4_9c_new_validated_source_manifests": new_validated_source_manifests,
            "r4_9c_rows_available_total": rows_available_total,
            "r4_9c_new_rows_available": new_rows_available,
            "r4_9c_delivery_blockers": delivery_blockers,
            "r4_9c_manual_files_still_required": manual_files_still_required,
            "r4_9c_physical_validated_files_still_missing": physical_validated_files_still_missing,
            "r4_9c_forbidden_artifact_usage": forbidden_artifact_usage,
            "production_status": production_status,
            "row_fabrication_policy": row_fabrication_policy,
            "phase_7_8_blocked": phase_7_8_blocked,
        }
    )
    write_json(exports_dir / "rebuild_status.json", rebuild_status)

    return status_payload
