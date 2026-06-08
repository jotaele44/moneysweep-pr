"""R4.9F source delivery watch and unfreeze candidate detection."""

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
from contract_sweeper.pipeline.delivered_source_validation import (
    contains_forbidden_token,
    discover_candidate_paths,
    relative_posix,
    sha256,
    validate_candidate,
)
from contract_sweeper.pipeline.unfreeze_guard import (
    downstream_blockers_preserved,
    evaluate_r49f_gate,
    retry_suppression_preserved,
)

FORBIDDEN_ARTIFACT_TOKENS = (
    "report",
    "summary",
    "graph",
    "network",
    "top_nodes",
    "top_node",
    "power_network",
    "dominance",
    "risk_alert",
    "investigative",
)


def _contains_forbidden_token(text: str) -> bool:
    lowered = str(text or "").lower()
    return any(token in lowered for token in FORBIDDEN_ARTIFACT_TOKENS)


def _preserved_blocker_rows(
    rows: list[dict[str, Any]],
    generated_at: str,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        out.append(
            {
                "generated_at": generated_at,
                "phase_code": str(row.get("phase_code", "")).strip(),
                "blocked": str(row.get("blocked", "")).strip() or "True",
                "blocker_reason": str(row.get("blocker_reason", "")).strip(),
                "unfreeze_condition": str(row.get("unfreeze_condition", "")).strip(),
                "status": str(row.get("status", "")).strip() or "blocked",
            }
        )
    return out


def run_source_delivery_watch(root: Path) -> dict[str, Any]:
    root = Path(root)
    exports_dir = root / "data" / "exports"
    review_dir = root / "data" / "review_queue"

    docs_handoff = root / "docs" / "SOURCE_DELIVERY_HANDOFF_R4_9E.md"
    docs_freeze = root / "docs" / "EXTERNAL_BLOCKER_FREEZE_STATUS_R4_9E.md"
    docs_present = docs_handoff.exists() and docs_freeze.exists()

    _ = read_json(exports_dir / "source_delivery_handoff_status_r4_9e.json")
    checklist_rows = read_csv(review_dir / "source_delivery_checklist_r4_9e.csv")
    _ = read_csv(review_dir / "unfreeze_trigger_conditions_r4_9e.csv")
    retry_suppression_rows = read_csv(review_dir / "retry_suppression_queue_r4_9d.csv")
    downstream_blocker_rows = read_csv(review_dir / "downstream_phase_blockers_r4_9d.csv")
    rebuild_status = read_json(exports_dir / "rebuild_status.json")

    generated_at = utc_now()
    forbidden_artifact_usage = False

    result_rows: list[dict[str, Any]] = []
    unfreeze_candidate_rows: list[dict[str, Any]] = []
    still_missing_rows: list[dict[str, Any]] = []

    checklist_rows_checked = 0
    candidate_files_found = 0
    candidate_rows_evaluated = 0
    sources_with_valid_candidate: set[str] = set()

    for checklist in checklist_rows:
        checklist_rows_checked += 1

        expected_input = str(checklist.get("expected_input", "")).strip()
        source_family = str(checklist.get("source_family", "")).strip()
        blocker_class = str(checklist.get("blocker_class", "")).strip()
        target_dropzone_path = str(checklist.get("target_dropzone_path", "")).strip()
        target_output_path = str(checklist.get("target_output_path", "")).strip()
        accepted_patterns = str(checklist.get("accepted_filename_patterns", "")).strip()
        required_columns = str(checklist.get("required_columns", "")).strip()
        validation_command = str(checklist.get("validation_command", "")).strip()
        unfreeze_condition = str(checklist.get("unfreeze_condition", "")).strip()

        for raw_path in (expected_input, target_dropzone_path, target_output_path):
            if _contains_forbidden_token(raw_path):
                forbidden_artifact_usage = True

        request = {
            "target_output_path": target_output_path or expected_input,
            "source_file": expected_input or target_output_path,
            "manifest_path": "",
            "target_dropzone_path": target_dropzone_path,
        }
        candidates = discover_candidate_paths(root, request)
        candidate_files_found += len(candidates)

        valid_candidate_for_source = False
        first_failure_reason = ""

        if not candidates:
            still_missing_rows.append(
                {
                    "expected_input": expected_input,
                    "source_family": source_family,
                    "blocker_class": blocker_class,
                    "target_dropzone_path": target_dropzone_path,
                    "target_output_path": target_output_path,
                    "missing_reason": "source_file_not_found",
                    "next_action": "await_external_source_delivery",
                    "validation_command": validation_command,
                    "unfreeze_condition": unfreeze_condition,
                }
            )
            result_rows.append(
                {
                    "generated_at": generated_at,
                    "expected_input": expected_input,
                    "source_family": source_family,
                    "blocker_class": blocker_class,
                    "candidate_path": "",
                    "candidate_relpath": "",
                    "candidate_filename": "",
                    "candidate_found": False,
                    "candidate_valid": False,
                    "candidate_row_count": 0,
                    "candidate_sha256": "",
                    "validation_result": "missing",
                    "validation_reason": "source_file_not_found",
                    "watch_status": "still_missing",
                    "unfreeze_candidate": False,
                }
            )
            continue

        for candidate in candidates:
            candidate_rows_evaluated += 1

            candidate_valid, details, fail_reason = validate_candidate(
                root=root,
                candidate=candidate,
                expected_sha256="",
                accepted_filename_patterns=accepted_patterns,
                required_columns=required_columns,
            )

            candidate_sha = str(details.get("candidate_sha256", "")).strip() or sha256(candidate)
            candidate_rows = safe_int(details.get("candidate_row_count"))
            if not candidate_valid and not first_failure_reason:
                first_failure_reason = fail_reason or "candidate_validation_failed"

            if contains_forbidden_token(str(candidate)):
                forbidden_artifact_usage = True

            result_rows.append(
                {
                    "generated_at": generated_at,
                    "expected_input": expected_input,
                    "source_family": source_family,
                    "blocker_class": blocker_class,
                    "candidate_path": str(candidate),
                    "candidate_relpath": relative_posix(root, candidate),
                    "candidate_filename": candidate.name,
                    "candidate_found": True,
                    "candidate_valid": candidate_valid,
                    "candidate_row_count": candidate_rows,
                    "candidate_sha256": candidate_sha,
                    "validation_result": "valid" if candidate_valid else "rejected",
                    "validation_reason": "validated"
                    if candidate_valid
                    else (fail_reason or "rejected"),
                    "watch_status": "unfreeze_candidate" if candidate_valid else "still_missing",
                    "unfreeze_candidate": candidate_valid,
                }
            )

            if candidate_valid:
                valid_candidate_for_source = True
                sources_with_valid_candidate.add(expected_input)
                unfreeze_candidate_rows.append(
                    {
                        "expected_input": expected_input,
                        "source_family": source_family,
                        "blocker_class": blocker_class,
                        "candidate_path": str(candidate),
                        "candidate_relpath": relative_posix(root, candidate),
                        "candidate_filename": candidate.name,
                        "candidate_row_count": candidate_rows,
                        "candidate_sha256": candidate_sha,
                        "validation_command": validation_command,
                        "unfreeze_condition": unfreeze_condition,
                    }
                )
                break

        if not valid_candidate_for_source:
            still_missing_rows.append(
                {
                    "expected_input": expected_input,
                    "source_family": source_family,
                    "blocker_class": blocker_class,
                    "target_dropzone_path": target_dropzone_path,
                    "target_output_path": target_output_path,
                    "missing_reason": first_failure_reason or "candidate_validation_failed",
                    "next_action": "await_valid_source_delivery",
                    "validation_command": validation_command,
                    "unfreeze_condition": unfreeze_condition,
                }
            )

    unfreeze_candidates = len(sources_with_valid_candidate)
    sources_still_missing = len(still_missing_rows)

    retry_suppression_ok = retry_suppression_preserved(
        retry_suppression_rows=retry_suppression_rows,
        checklist_rows_checked=checklist_rows_checked,
        unfreeze_candidates=unfreeze_candidates,
    )
    downstream_blockers_ok = downstream_blockers_preserved(downstream_blocker_rows)

    downloads_executed = False
    rows_ingested = 0
    production_inputs_staged = 0
    production_status = "NON_PRODUCTION_DIAGNOSTIC"
    row_fabrication_policy = str(
        rebuild_status.get("row_fabrication_policy") or "FORBIDDEN_NO_SYNTHETIC_ROWS"
    )
    phase_7_8_blocked = bool(rebuild_status.get("phase_7_8_blocked", True))

    gate_passed = evaluate_r49f_gate(
        checklist_rows_total=len(checklist_rows),
        checklist_rows_checked=checklist_rows_checked,
        candidate_files_found=candidate_files_found,
        candidate_rows_evaluated=candidate_rows_evaluated,
        sources_still_missing=sources_still_missing,
        retry_suppression_ok=retry_suppression_ok,
        downstream_blockers_ok=downstream_blockers_ok,
        downloads_executed=downloads_executed,
        rows_ingested=rows_ingested,
        production_inputs_staged=production_inputs_staged,
        forbidden_artifact_usage=forbidden_artifact_usage,
        production_status=production_status,
        row_fabrication_policy=row_fabrication_policy,
        phase_7_8_blocked=phase_7_8_blocked,
    )
    gate_passed = bool(gate_passed and docs_present)

    status_payload = {
        "generated_at": generated_at,
        "r4_9f_gate_passed": gate_passed,
        "r4_9f_checklist_rows_checked": checklist_rows_checked,
        "r4_9f_candidate_files_found": candidate_files_found,
        "r4_9f_unfreeze_candidates": unfreeze_candidates,
        "r4_9f_sources_still_missing": sources_still_missing,
        "r4_9f_retry_suppression_preserved": retry_suppression_ok,
        "r4_9f_downstream_blockers_preserved": downstream_blockers_ok,
        "r4_9f_downloads_executed": downloads_executed,
        "r4_9f_rows_ingested": rows_ingested,
        "r4_9f_production_inputs_staged": production_inputs_staged,
        "r4_9f_forbidden_artifact_usage": forbidden_artifact_usage,
        "production_status": production_status,
        "row_fabrication_policy": row_fabrication_policy,
        "phase_7_8_blocked": phase_7_8_blocked,
    }

    write_json(exports_dir / "source_delivery_watch_status_r4_9f.json", status_payload)
    write_csv(
        exports_dir / "source_delivery_watch_results_r4_9f.csv",
        result_rows,
        [
            "generated_at",
            "expected_input",
            "source_family",
            "blocker_class",
            "candidate_path",
            "candidate_relpath",
            "candidate_filename",
            "candidate_found",
            "candidate_valid",
            "candidate_row_count",
            "candidate_sha256",
            "validation_result",
            "validation_reason",
            "watch_status",
            "unfreeze_candidate",
        ],
    )
    write_csv(
        review_dir / "unfreeze_candidates_r4_9f.csv",
        unfreeze_candidate_rows,
        [
            "expected_input",
            "source_family",
            "blocker_class",
            "candidate_path",
            "candidate_relpath",
            "candidate_filename",
            "candidate_row_count",
            "candidate_sha256",
            "validation_command",
            "unfreeze_condition",
        ],
    )
    write_csv(
        review_dir / "source_delivery_still_missing_r4_9f.csv",
        still_missing_rows,
        [
            "expected_input",
            "source_family",
            "blocker_class",
            "target_dropzone_path",
            "target_output_path",
            "missing_reason",
            "next_action",
            "validation_command",
            "unfreeze_condition",
        ],
    )
    write_csv(
        review_dir / "downstream_phase_blockers_r4_9f.csv",
        _preserved_blocker_rows(downstream_blocker_rows, generated_at),
        [
            "generated_at",
            "phase_code",
            "blocked",
            "blocker_reason",
            "unfreeze_condition",
            "status",
        ],
    )

    rebuild_status.update(
        {
            "r4_9f_generated_at": generated_at,
            "r4_9f_gate_passed": gate_passed,
            "r4_9f_checklist_rows_checked": checklist_rows_checked,
            "r4_9f_candidate_files_found": candidate_files_found,
            "r4_9f_unfreeze_candidates": unfreeze_candidates,
            "r4_9f_sources_still_missing": sources_still_missing,
            "r4_9f_retry_suppression_preserved": retry_suppression_ok,
            "r4_9f_downstream_blockers_preserved": downstream_blockers_ok,
            "r4_9f_downloads_executed": downloads_executed,
            "r4_9f_rows_ingested": rows_ingested,
            "r4_9f_production_inputs_staged": production_inputs_staged,
            "r4_9f_forbidden_artifact_usage": forbidden_artifact_usage,
            "production_status": production_status,
            "row_fabrication_policy": row_fabrication_policy,
            "phase_7_8_blocked": phase_7_8_blocked,
        }
    )
    write_json(exports_dir / "rebuild_status.json", rebuild_status)

    return status_payload
