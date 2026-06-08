"""R4.9Z source recovery pause and status lock."""

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
    write_markdown,
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


def _is_truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in {"true", "1", "yes"}


def _render_pause_doc(
    *,
    generated_at: str,
    pause_lock_active: bool,
    unfreeze_candidates: int,
    sources_still_missing: int,
    retry_suppression_active: bool,
    downstream_blockers_active: bool,
) -> str:
    return (
        "# Source Recovery Pause Status (R4.9Z)\n\n"
        f"Generated at: {generated_at}\n\n"
        "## Current State\n\n"
        f"- pause_lock_active: {pause_lock_active}\n"
        f"- unfreeze_candidates: {unfreeze_candidates}\n"
        f"- sources_still_missing: {sources_still_missing}\n"
        f"- retry_suppression_active: {retry_suppression_active}\n"
        f"- downstream_blockers_active: {downstream_blockers_active}\n\n"
        "## Blocked Scope\n\n"
        "- Source retries are paused.\n"
        "- No downstream progression to R5/R6/R7/R8.\n"
        "- Production status remains NON_PRODUCTION_DIAGNOSTIC.\n"
        "- Phase 7/8 remains blocked.\n\n"
        "## External Deliveries Required\n\n"
        "- Deliver missing source files listed in `data/review_queue/source_recovery_resume_conditions_r4_9z.csv`.\n"
        "- Each delivered file must pass filename, schema, nonzero rows, and SHA256 checks.\n"
        "- Material source availability change is required before retries are resumed.\n\n"
        "## Resume Conditions\n\n"
        "1. At least one valid unfreeze candidate is present.\n"
        "2. Source remains in approved path and is not a forbidden artifact.\n"
        "3. Validation command can pass for delivered file.\n"
        "4. Retry suppression can be safely lifted for the resolved source only.\n"
        "5. Downstream blockers remain until broader source coverage improves.\n"
    )


def run_source_recovery_pause_lock(root: Path) -> dict[str, Any]:
    root = Path(root)
    exports_dir = root / "data" / "exports"
    review_dir = root / "data" / "review_queue"

    watch_status = read_json(exports_dir / "source_delivery_watch_status_r4_9f.json")
    _ = read_csv(exports_dir / "source_delivery_watch_results_r4_9f.csv")
    unfreeze_candidates_rows = read_csv(review_dir / "unfreeze_candidates_r4_9f.csv")
    still_missing_rows = read_csv(review_dir / "source_delivery_still_missing_r4_9f.csv")
    downstream_rows = read_csv(review_dir / "downstream_phase_blockers_r4_9f.csv")
    rebuild_status = read_json(exports_dir / "rebuild_status.json")

    handoff_doc_exists = (root / "docs" / "SOURCE_DELIVERY_HANDOFF_R4_9E.md").exists()
    freeze_doc_exists = (root / "docs" / "EXTERNAL_BLOCKER_FREEZE_STATUS_R4_9E.md").exists()

    generated_at = utc_now()
    forbidden_artifact_usage = False

    # Required confirmations from R4.9F state.
    unfreeze_candidates = max(
        safe_int(watch_status.get("r4_9f_unfreeze_candidates")),
        len(unfreeze_candidates_rows),
    )
    sources_still_missing = max(
        safe_int(watch_status.get("r4_9f_sources_still_missing")),
        len(still_missing_rows),
    )
    retry_suppression_active = bool(watch_status.get("r4_9f_retry_suppression_preserved", False))
    downstream_blockers_active = bool(
        watch_status.get("r4_9f_downstream_blockers_preserved", False)
    )
    if not downstream_blockers_active:
        downstream_blockers_active = bool(downstream_rows) and all(
            _is_truthy(row.get("blocked")) for row in downstream_rows
        )

    pause_matrix_rows: list[dict[str, Any]] = []
    resume_rows: list[dict[str, Any]] = []
    for row in still_missing_rows:
        expected_input = str(row.get("expected_input", "")).strip()
        source_family = str(row.get("source_family", "")).strip()
        blocker_class = str(row.get("blocker_class", "")).strip()
        target_dropzone_path = str(row.get("target_dropzone_path", "")).strip()
        target_output_path = str(row.get("target_output_path", "")).strip()
        missing_reason = str(row.get("missing_reason", "")).strip() or "source_file_not_found"
        validation_command = str(row.get("validation_command", "")).strip()
        unfreeze_condition = str(row.get("unfreeze_condition", "")).strip()

        for raw_path in (expected_input, target_dropzone_path, target_output_path):
            if _contains_forbidden_token(raw_path):
                forbidden_artifact_usage = True

        pause_matrix_rows.append(
            {
                "generated_at": generated_at,
                "expected_input": expected_input,
                "source_family": source_family,
                "blocker_class": blocker_class,
                "missing_reason": missing_reason,
                "pause_status": "PAUSED_EXTERNAL_DELIVERY_REQUIRED",
                "retry_status": "SUPPRESSED",
                "target_dropzone_path": target_dropzone_path,
                "target_output_path": target_output_path,
                "unfreeze_condition": unfreeze_condition,
            }
        )
        resume_rows.append(
            {
                "expected_input": expected_input,
                "source_family": source_family,
                "blocker_class": blocker_class,
                "target_dropzone_path": target_dropzone_path,
                "target_output_path": target_output_path,
                "required_delivery": "file_delivered",
                "required_schema_check": "required_columns_present",
                "required_row_check": "nonzero_rows",
                "required_hash_check": "sha256_computed",
                "required_manifest_check": "validated_manifest_written",
                "validation_command": validation_command,
                "resume_condition": unfreeze_condition
                or "deliver file + pass validation + resolve blocker",
            }
        )

    downstream_r49z_rows: list[dict[str, Any]] = []
    for row in downstream_rows:
        downstream_r49z_rows.append(
            {
                "generated_at": generated_at,
                "phase_code": str(row.get("phase_code", "")).strip(),
                "blocked": str(row.get("blocked", "")).strip() or "True",
                "blocker_reason": str(row.get("blocker_reason", "")).strip(),
                "unfreeze_condition": str(row.get("unfreeze_condition", "")).strip(),
                "status": "blocked",
                "pause_lock_active": True,
            }
        )

    pause_lock_active = bool(
        handoff_doc_exists
        and freeze_doc_exists
        and retry_suppression_active
        and downstream_blockers_active
        and unfreeze_candidates == 0
        and sources_still_missing == 21
    )

    downloads_executed = False
    rows_ingested = 0
    production_inputs_staged = 0
    production_status = "NON_PRODUCTION_DIAGNOSTIC"
    row_fabrication_policy = str(
        rebuild_status.get("row_fabrication_policy") or "FORBIDDEN_NO_SYNTHETIC_ROWS"
    )
    phase_7_8_blocked = bool(rebuild_status.get("phase_7_8_blocked", True))

    gate_passed = bool(
        pause_lock_active
        and unfreeze_candidates == 0
        and sources_still_missing == 21
        and retry_suppression_active
        and downstream_blockers_active
        and not downloads_executed
        and rows_ingested == 0
        and production_inputs_staged == 0
        and not forbidden_artifact_usage
        and production_status == "NON_PRODUCTION_DIAGNOSTIC"
        and row_fabrication_policy == "FORBIDDEN_NO_SYNTHETIC_ROWS"
        and phase_7_8_blocked
    )

    status_payload = {
        "generated_at": generated_at,
        "r4_9z_gate_passed": gate_passed,
        "r4_9z_pause_lock_active": pause_lock_active,
        "r4_9z_unfreeze_candidates": unfreeze_candidates,
        "r4_9z_sources_still_missing": sources_still_missing,
        "r4_9z_retry_suppression_active": retry_suppression_active,
        "r4_9z_downstream_blockers_active": downstream_blockers_active,
        "r4_9z_downloads_executed": downloads_executed,
        "r4_9z_rows_ingested": rows_ingested,
        "r4_9z_production_inputs_staged": production_inputs_staged,
        "r4_9z_forbidden_artifact_usage": forbidden_artifact_usage,
        "production_status": production_status,
        "row_fabrication_policy": row_fabrication_policy,
        "phase_7_8_blocked": phase_7_8_blocked,
    }

    write_markdown(
        root / "docs" / "SOURCE_RECOVERY_PAUSE_STATUS_R4_9Z.md",
        _render_pause_doc(
            generated_at=generated_at,
            pause_lock_active=pause_lock_active,
            unfreeze_candidates=unfreeze_candidates,
            sources_still_missing=sources_still_missing,
            retry_suppression_active=retry_suppression_active,
            downstream_blockers_active=downstream_blockers_active,
        ),
    )
    write_json(exports_dir / "source_recovery_pause_status_r4_9z.json", status_payload)
    write_csv(
        exports_dir / "source_recovery_pause_matrix_r4_9z.csv",
        pause_matrix_rows,
        [
            "generated_at",
            "expected_input",
            "source_family",
            "blocker_class",
            "missing_reason",
            "pause_status",
            "retry_status",
            "target_dropzone_path",
            "target_output_path",
            "unfreeze_condition",
        ],
    )
    write_csv(
        review_dir / "source_recovery_resume_conditions_r4_9z.csv",
        resume_rows,
        [
            "expected_input",
            "source_family",
            "blocker_class",
            "target_dropzone_path",
            "target_output_path",
            "required_delivery",
            "required_schema_check",
            "required_row_check",
            "required_hash_check",
            "required_manifest_check",
            "validation_command",
            "resume_condition",
        ],
    )
    write_csv(
        review_dir / "downstream_phase_blockers_r4_9z.csv",
        downstream_r49z_rows,
        [
            "generated_at",
            "phase_code",
            "blocked",
            "blocker_reason",
            "unfreeze_condition",
            "status",
            "pause_lock_active",
        ],
    )

    rebuild_status.update(
        {
            "r4_9z_generated_at": generated_at,
            "r4_9z_gate_passed": gate_passed,
            "r4_9z_pause_lock_active": pause_lock_active,
            "r4_9z_unfreeze_candidates": unfreeze_candidates,
            "r4_9z_sources_still_missing": sources_still_missing,
            "r4_9z_retry_suppression_active": retry_suppression_active,
            "r4_9z_downstream_blockers_active": downstream_blockers_active,
            "r4_9z_downloads_executed": downloads_executed,
            "r4_9z_rows_ingested": rows_ingested,
            "r4_9z_production_inputs_staged": production_inputs_staged,
            "r4_9z_forbidden_artifact_usage": forbidden_artifact_usage,
            "production_status": production_status,
            "row_fabrication_policy": row_fabrication_policy,
            "phase_7_8_blocked": phase_7_8_blocked,
        }
    )
    write_json(exports_dir / "rebuild_status.json", rebuild_status)

    return status_payload
