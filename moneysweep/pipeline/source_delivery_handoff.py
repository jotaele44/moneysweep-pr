"""R4.9E source delivery handoff and operator checklist generation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from moneysweep.pipeline.acquisition_package import (
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


def _blocker_key(row: dict[str, Any]) -> str:
    expected_input = str(row.get("expected_input", "")).strip()
    source_family = str(row.get("source_family", "")).strip()
    blocker_class = str(row.get("blocker_class", "")).strip()
    return f"{expected_input}|{source_family}|{blocker_class}"


def _render_handoff_doc(
    *,
    generated_at: str,
    blockers_total: int,
    manual_count: int,
    physical_count: int,
    retry_suppressed: int,
    downstream_blockers: int,
) -> str:
    return (
        "# Source Delivery Handoff (R4.9E)\n\n"
        f"Generated at: {generated_at}\n\n"
        "## Objective\n\n"
        "Create an operator-ready delivery checklist from the frozen external blocker state without running downloads, ingest, or staging.\n\n"
        "## Current Frozen State\n\n"
        f"- blockers_frozen: {blockers_total}\n"
        f"- manual_file_required: {manual_count}\n"
        f"- physical_validated_file_missing: {physical_count}\n"
        f"- retry_suppressed: {retry_suppressed}\n"
        f"- downstream_phases_blocked: {downstream_blockers}\n\n"
        "## Operator Workflow\n\n"
        "1. Deliver each missing source file into the listed dropzone or validated target path.\n"
        "2. Ensure filename pattern and required columns match checklist requirements.\n"
        "3. Run the listed validation command for each delivered source.\n"
        "4. Verify nonzero rows and SHA256 before unfreezing retry suppression.\n"
        "5. Write or update validated source manifests for each accepted delivery.\n\n"
        "## Guardrails\n\n"
        "- No source delivery means no unfreeze.\n"
        "- No schema/hash/row validation means no staging.\n"
        "- Production status remains NON_PRODUCTION_DIAGNOSTIC until gates pass.\n"
        "- Phase 7/8 remains blocked.\n"
    )


def _render_freeze_status_doc(
    *,
    generated_at: str,
    blockers_total: int,
    checklist_count: int,
    unfreeze_trigger_count: int,
    retry_preserved: bool,
    downstream_preserved: bool,
) -> str:
    return (
        "# External Blocker Freeze Status (R4.9E)\n\n"
        f"Generated at: {generated_at}\n\n"
        "R4.9D freeze state is carried forward unchanged for operator handoff.\n\n"
        "## Preservation Checks\n\n"
        f"- frozen_blockers_count: {blockers_total}\n"
        f"- delivery_checklist_count: {checklist_count}\n"
        f"- unfreeze_trigger_count: {unfreeze_trigger_count}\n"
        f"- retry_suppression_preserved: {retry_preserved}\n"
        f"- downstream_blockers_preserved: {downstream_preserved}\n\n"
        "## Phase State\n\n"
        "- This phase is documentation and handoff only.\n"
        "- No downloads executed.\n"
        "- No rows ingested.\n"
        "- No production inputs staged.\n"
        "- Production status remains NON_PRODUCTION_DIAGNOSTIC.\n"
        "- Phase 7/8 remains blocked.\n"
    )


def run_source_delivery_handoff(root: Path) -> dict[str, Any]:
    root = Path(root)
    exports_dir = root / "data" / "exports"
    review_dir = root / "data" / "review_queue"

    freeze_status = read_json(exports_dir / "external_blocker_freeze_status_r4_9d.json")
    freeze_rows = read_csv(exports_dir / "external_blocker_freeze_matrix_r4_9d.csv")
    unfreeze_requirements_path = (
        root / "data" / "exports" / "source_recovery_unfreeze_requirements_r4_9d.md"
    )
    source_delivery_rows = read_csv(review_dir / "source_delivery_required_r4_9d.csv")
    retry_suppression_rows = read_csv(review_dir / "retry_suppression_queue_r4_9d.csv")
    downstream_blocker_rows = read_csv(review_dir / "downstream_phase_blockers_r4_9d.csv")
    rebuild_status = read_json(exports_dir / "rebuild_status.json")

    source_delivery_by_key = {_blocker_key(row): row for row in source_delivery_rows}
    retry_by_expected = {
        str(row.get("expected_input", "")).strip(): row for row in retry_suppression_rows
    }

    checklist_rows: list[dict[str, Any]] = []
    unfreeze_rows: list[dict[str, Any]] = []
    summary_rows: list[dict[str, Any]] = []

    forbidden_artifact_usage = False
    generated_at = utc_now()

    for row in freeze_rows:
        key = _blocker_key(row)
        source_row = source_delivery_by_key.get(key, {})

        expected_input = str(row.get("expected_input", "")).strip()
        source_family = str(row.get("source_family", "")).strip()
        blocker_class = str(row.get("blocker_class", "")).strip()
        target_dropzone_path = str(
            row.get("target_dropzone_path") or source_row.get("target_dropzone_path") or ""
        ).strip()
        target_output_path = str(
            row.get("target_output_path") or source_row.get("target_output_path") or ""
        ).strip()
        accepted_filename_patterns = str(
            row.get("accepted_filename_patterns")
            or source_row.get("accepted_filename_patterns")
            or ""
        ).strip()
        required_columns = str(
            row.get("required_columns") or source_row.get("required_columns") or ""
        ).strip()
        validation_command = str(
            row.get("validation_command") or source_row.get("validation_command") or ""
        ).strip()
        unfreeze_condition = str(
            row.get("unfreeze_condition") or source_row.get("unfreeze_condition") or ""
        ).strip()
        reason_blocked = str(
            row.get("reason_blocked") or source_row.get("reason_blocked") or ""
        ).strip()

        for raw_path in (
            expected_input,
            target_dropzone_path,
            target_output_path,
        ):
            if _contains_forbidden_token(raw_path):
                forbidden_artifact_usage = True

        checklist_row = {
            "expected_input": expected_input,
            "source_family": source_family,
            "blocker_class": blocker_class,
            "target_dropzone_path": target_dropzone_path,
            "target_output_path": target_output_path,
            "accepted_filename_patterns": accepted_filename_patterns,
            "required_columns": required_columns,
            "validation_command": validation_command,
            "unfreeze_condition": unfreeze_condition,
            "reason_blocked": reason_blocked,
        }
        checklist_rows.append(checklist_row)

        unfreeze_rows.append(
            {
                "expected_input": expected_input,
                "source_family": source_family,
                "blocker_class": blocker_class,
                "trigger_file_delivered": True,
                "trigger_schema_valid": True,
                "trigger_nonzero_rows": True,
                "trigger_sha256_computed": True,
                "trigger_manifest_written": True,
                "trigger_blocker_resolved": True,
                "validation_command": validation_command,
                "unfreeze_condition": unfreeze_condition,
                "trigger_status": "pending_external_delivery",
            }
        )

        retry_row = retry_by_expected.get(expected_input, {})
        summary_rows.append(
            {
                "generated_at": generated_at,
                "expected_input": expected_input,
                "source_family": source_family,
                "blocker_class": blocker_class,
                "delivery_status": "pending_external_delivery",
                "unfreeze_condition": unfreeze_condition,
                "retry_suppressed": str(retry_row.get("suppression_status", "")).strip()
                == "suppressed",
                "production_status": "NON_PRODUCTION_DIAGNOSTIC",
                "phase_7_8_blocked": True,
            }
        )

    frozen_keys = {_blocker_key(row) for row in freeze_rows}
    checklist_keys = {_blocker_key(row) for row in checklist_rows}
    every_frozen_blocker_in_checklist = frozen_keys == checklist_keys and len(freeze_rows) == len(
        checklist_rows
    )
    every_blocker_has_unfreeze = all(
        bool(str(row.get("unfreeze_condition", "")).strip()) for row in checklist_rows
    )

    retry_suppressed_count = sum(
        1
        for row in retry_suppression_rows
        if str(row.get("suppression_status", "")).strip().lower() == "suppressed"
    )
    retry_suppression_preserved = retry_suppressed_count >= len(freeze_rows) and len(
        retry_suppression_rows
    ) >= len(freeze_rows)

    downstream_blockers_preserved = bool(downstream_blocker_rows) and all(
        str(row.get("blocked", "")).strip().lower() in {"true", "1", "yes"}
        for row in downstream_blocker_rows
    )

    docs_handoff = root / "docs" / "SOURCE_DELIVERY_HANDOFF_R4_9E.md"
    docs_freeze = root / "docs" / "EXTERNAL_BLOCKER_FREEZE_STATUS_R4_9E.md"
    write_markdown(
        docs_handoff,
        _render_handoff_doc(
            generated_at=generated_at,
            blockers_total=len(freeze_rows),
            manual_count=safe_int(freeze_status.get("r4_9d_manual_file_required")),
            physical_count=safe_int(freeze_status.get("r4_9d_physical_validated_file_missing")),
            retry_suppressed=safe_int(freeze_status.get("r4_9d_retry_suppressed")),
            downstream_blockers=safe_int(freeze_status.get("r4_9d_downstream_phases_blocked")),
        ),
    )
    write_markdown(
        docs_freeze,
        _render_freeze_status_doc(
            generated_at=generated_at,
            blockers_total=len(freeze_rows),
            checklist_count=len(checklist_rows),
            unfreeze_trigger_count=len(unfreeze_rows),
            retry_preserved=retry_suppression_preserved,
            downstream_preserved=downstream_blockers_preserved,
        ),
    )
    handoff_written = docs_handoff.exists() and docs_freeze.exists()

    downloads_executed = False
    rows_ingested = 0
    production_inputs_staged = 0
    production_status = "NON_PRODUCTION_DIAGNOSTIC"
    row_fabrication_policy = str(
        rebuild_status.get("row_fabrication_policy") or "FORBIDDEN_NO_SYNTHETIC_ROWS"
    )
    phase_7_8_blocked = bool(rebuild_status.get("phase_7_8_blocked", True))

    gate_passed = bool(
        handoff_written
        and unfreeze_requirements_path.exists()
        and every_frozen_blocker_in_checklist
        and every_blocker_has_unfreeze
        and retry_suppression_preserved
        and downstream_blockers_preserved
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
        "r4_9e_gate_passed": gate_passed,
        "r4_9e_handoff_written": handoff_written,
        "r4_9e_delivery_checklist_count": len(checklist_rows),
        "r4_9e_unfreeze_trigger_count": len(unfreeze_rows),
        "r4_9e_retry_suppression_preserved": retry_suppression_preserved,
        "r4_9e_downstream_blockers_preserved": downstream_blockers_preserved,
        "r4_9e_downloads_executed": downloads_executed,
        "r4_9e_rows_ingested": rows_ingested,
        "r4_9e_production_inputs_staged": production_inputs_staged,
        "r4_9e_forbidden_artifact_usage": forbidden_artifact_usage,
        "production_status": production_status,
        "row_fabrication_policy": row_fabrication_policy,
        "phase_7_8_blocked": phase_7_8_blocked,
    }

    write_json(exports_dir / "source_delivery_handoff_status_r4_9e.json", status_payload)
    write_csv(
        exports_dir / "source_delivery_handoff_summary_r4_9e.csv",
        summary_rows,
        [
            "generated_at",
            "expected_input",
            "source_family",
            "blocker_class",
            "delivery_status",
            "unfreeze_condition",
            "retry_suppressed",
            "production_status",
            "phase_7_8_blocked",
        ],
    )
    write_csv(
        review_dir / "source_delivery_checklist_r4_9e.csv",
        checklist_rows,
        [
            "expected_input",
            "source_family",
            "blocker_class",
            "target_dropzone_path",
            "target_output_path",
            "accepted_filename_patterns",
            "required_columns",
            "validation_command",
            "unfreeze_condition",
            "reason_blocked",
        ],
    )
    write_csv(
        review_dir / "unfreeze_trigger_conditions_r4_9e.csv",
        unfreeze_rows,
        [
            "expected_input",
            "source_family",
            "blocker_class",
            "trigger_file_delivered",
            "trigger_schema_valid",
            "trigger_nonzero_rows",
            "trigger_sha256_computed",
            "trigger_manifest_written",
            "trigger_blocker_resolved",
            "validation_command",
            "unfreeze_condition",
            "trigger_status",
        ],
    )

    rebuild_status.update(
        {
            "r4_9e_generated_at": generated_at,
            "r4_9e_gate_passed": gate_passed,
            "r4_9e_handoff_written": handoff_written,
            "r4_9e_delivery_checklist_count": len(checklist_rows),
            "r4_9e_unfreeze_trigger_count": len(unfreeze_rows),
            "r4_9e_retry_suppression_preserved": retry_suppression_preserved,
            "r4_9e_downstream_blockers_preserved": downstream_blockers_preserved,
            "r4_9e_downloads_executed": downloads_executed,
            "r4_9e_rows_ingested": rows_ingested,
            "r4_9e_production_inputs_staged": production_inputs_staged,
            "r4_9e_forbidden_artifact_usage": forbidden_artifact_usage,
            "production_status": production_status,
            "row_fabrication_policy": row_fabrication_policy,
            "phase_7_8_blocked": phase_7_8_blocked,
        }
    )
    write_json(exports_dir / "rebuild_status.json", rebuild_status)

    return status_payload
