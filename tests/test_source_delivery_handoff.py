"""Tests for R4.9E source delivery handoff and operator checklist outputs."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from moneysweep.pipeline.source_delivery_handoff import run_source_delivery_handoff


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _load_csv_rows(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _bootstrap(tmp_path: Path) -> None:
    _write_json(
        tmp_path / "data" / "exports" / "external_blocker_freeze_status_r4_9d.json",
        {
            "r4_9d_gate_passed": True,
            "r4_9d_blockers_frozen": 2,
            "r4_9d_manual_file_required": 1,
            "r4_9d_physical_validated_file_missing": 1,
            "r4_9d_retry_suppressed": 2,
            "r4_9d_downstream_phases_blocked": 2,
            "production_status": "NON_PRODUCTION_DIAGNOSTIC",
            "phase_7_8_blocked": True,
        },
    )
    _write_csv(
        tmp_path / "data" / "exports" / "external_blocker_freeze_matrix_r4_9d.csv",
        [
            {
                "frozen_at": "2026-05-09T00:00:00Z",
                "request_id": "manual:data/staging/processed/pr_contracts_master.csv",
                "request_type": "manual_file_delivery",
                "source_family": "usaspending_federal_awards_backbone",
                "expected_input": "data/staging/processed/pr_contracts_master.csv",
                "target_output_path": "data/staging/processed/pr_contracts_master.csv",
                "target_dropzone_path": "data/manual_import_dropzone/r4_9d/usaspending/pr_contracts_master.csv",
                "accepted_filename_patterns": "pr_contracts_master.csv|*.csv",
                "required_columns": "award_id|recipient_name",
                "validation_command": "python -c \"print('validate contracts')\"",
                "blocker_class": "manual_file_required",
                "reason_blocked": "file_not_delivered",
                "next_action": "manual_source_delivery",
                "unfreeze_condition": "deliver manual file and validate",
                "retry_rank_hint": "1",
                "retry_reason_hint": "manual source missing",
            },
            {
                "frozen_at": "2026-05-09T00:00:00Z",
                "request_id": "validated:data/staging/processed/pr_doe_master.csv",
                "request_type": "validated_manifest_delivery",
                "source_family": "federal_sectoral_doe",
                "expected_input": "data/staging/processed/pr_doe_master.csv",
                "target_output_path": "data/staging/processed/pr_doe_master.csv",
                "target_dropzone_path": "",
                "accepted_filename_patterns": "",
                "required_columns": "award_id|recipient_name",
                "validation_command": "python -c \"print('validate doe')\"",
                "blocker_class": "physical_validated_file_missing",
                "reason_blocked": "file_not_delivered",
                "next_action": "physical_validated_source_delivery",
                "unfreeze_condition": "deliver validated physical file",
                "retry_rank_hint": "2",
                "retry_reason_hint": "validated source missing",
            },
        ],
        [
            "frozen_at",
            "request_id",
            "request_type",
            "source_family",
            "expected_input",
            "target_output_path",
            "target_dropzone_path",
            "accepted_filename_patterns",
            "required_columns",
            "validation_command",
            "blocker_class",
            "reason_blocked",
            "next_action",
            "unfreeze_condition",
            "retry_rank_hint",
            "retry_reason_hint",
        ],
    )
    _write_csv(
        tmp_path / "data" / "review_queue" / "source_delivery_required_r4_9d.csv",
        [
            {
                "expected_input": "data/staging/processed/pr_contracts_master.csv",
                "source_family": "usaspending_federal_awards_backbone",
                "target_output_path": "data/staging/processed/pr_contracts_master.csv",
                "target_dropzone_path": "data/manual_import_dropzone/r4_9d/usaspending/pr_contracts_master.csv",
                "accepted_filename_patterns": "pr_contracts_master.csv|*.csv",
                "required_columns": "award_id|recipient_name",
                "validation_command": "python -c \"print('validate contracts')\"",
                "reason_blocked": "file_not_delivered",
                "unfreeze_condition": "deliver manual file and validate",
                "blocker_class": "manual_file_required",
            },
            {
                "expected_input": "data/staging/processed/pr_doe_master.csv",
                "source_family": "federal_sectoral_doe",
                "target_output_path": "data/staging/processed/pr_doe_master.csv",
                "target_dropzone_path": "",
                "accepted_filename_patterns": "",
                "required_columns": "award_id|recipient_name",
                "validation_command": "python -c \"print('validate doe')\"",
                "reason_blocked": "file_not_delivered",
                "unfreeze_condition": "deliver validated physical file",
                "blocker_class": "physical_validated_file_missing",
            },
        ],
        [
            "expected_input",
            "source_family",
            "target_output_path",
            "target_dropzone_path",
            "accepted_filename_patterns",
            "required_columns",
            "validation_command",
            "reason_blocked",
            "unfreeze_condition",
            "blocker_class",
        ],
    )
    _write_csv(
        tmp_path / "data" / "review_queue" / "retry_suppression_queue_r4_9d.csv",
        [
            {
                "request_id": "manual:data/staging/processed/pr_contracts_master.csv",
                "expected_input": "data/staging/processed/pr_contracts_master.csv",
                "source_family": "usaspending_federal_awards_backbone",
                "suppression_status": "suppressed",
                "suppression_reason": "external_source_unavailable_or_undelivered",
                "suppression_scope": "block_generic_retry_loop",
                "unsuppress_condition": "deliver manual file and validate",
                "retry_allowed": "False",
            },
            {
                "request_id": "validated:data/staging/processed/pr_doe_master.csv",
                "expected_input": "data/staging/processed/pr_doe_master.csv",
                "source_family": "federal_sectoral_doe",
                "suppression_status": "suppressed",
                "suppression_reason": "external_source_unavailable_or_undelivered",
                "suppression_scope": "block_generic_retry_loop",
                "unsuppress_condition": "deliver validated physical file",
                "retry_allowed": "False",
            },
        ],
        [
            "request_id",
            "expected_input",
            "source_family",
            "suppression_status",
            "suppression_reason",
            "suppression_scope",
            "unsuppress_condition",
            "retry_allowed",
        ],
    )
    _write_csv(
        tmp_path / "data" / "review_queue" / "downstream_phase_blockers_r4_9d.csv",
        [
            {
                "phase_code": "R5_ENTITY_RESOLUTION",
                "blocked": "True",
                "blocker_reason": "R5 blocked",
                "unfreeze_condition": "clear external blockers",
                "status": "blocked",
            },
            {
                "phase_code": "R8_GRAPH_REBUILD",
                "blocked": "True",
                "blocker_reason": "R8 blocked",
                "unfreeze_condition": "clear external blockers",
                "status": "blocked",
            },
        ],
        ["phase_code", "blocked", "blocker_reason", "unfreeze_condition", "status"],
    )
    _write_json(
        tmp_path / "data" / "exports" / "rebuild_status.json",
        {
            "production_status": "NON_PRODUCTION_DIAGNOSTIC",
            "row_fabrication_policy": "FORBIDDEN_NO_SYNTHETIC_ROWS",
            "phase_7_8_blocked": True,
        },
    )
    (tmp_path / "data" / "exports" / "source_recovery_unfreeze_requirements_r4_9d.md").write_text(
        "# requirements",
        encoding="utf-8",
    )


def test_source_delivery_handoff_gate_passes(tmp_path: Path):
    _bootstrap(tmp_path)
    status = run_source_delivery_handoff(tmp_path)

    assert status["r4_9e_gate_passed"] is True
    assert status["r4_9e_handoff_written"] is True
    assert status["r4_9e_delivery_checklist_count"] == 2
    assert status["r4_9e_unfreeze_trigger_count"] == 2
    assert status["r4_9e_retry_suppression_preserved"] is True
    assert status["r4_9e_downstream_blockers_preserved"] is True
    assert status["r4_9e_downloads_executed"] is False
    assert status["r4_9e_rows_ingested"] == 0
    assert status["r4_9e_production_inputs_staged"] == 0
    assert status["r4_9e_forbidden_artifact_usage"] is False
    assert status["production_status"] == "NON_PRODUCTION_DIAGNOSTIC"
    assert status["phase_7_8_blocked"] is True

    checklist_rows = _load_csv_rows(
        tmp_path / "data" / "review_queue" / "source_delivery_checklist_r4_9e.csv"
    )
    assert len(checklist_rows) == 2
    triggers = _load_csv_rows(
        tmp_path / "data" / "review_queue" / "unfreeze_trigger_conditions_r4_9e.csv"
    )
    assert len(triggers) == 2

    assert (tmp_path / "docs" / "SOURCE_DELIVERY_HANDOFF_R4_9E.md").exists()
    assert (tmp_path / "docs" / "EXTERNAL_BLOCKER_FREEZE_STATUS_R4_9E.md").exists()


def test_source_delivery_handoff_fails_when_retry_suppression_missing(tmp_path: Path):
    _bootstrap(tmp_path)
    _write_csv(
        tmp_path / "data" / "review_queue" / "retry_suppression_queue_r4_9d.csv",
        [],
        [
            "request_id",
            "expected_input",
            "source_family",
            "suppression_status",
            "suppression_reason",
            "suppression_scope",
            "unsuppress_condition",
            "retry_allowed",
        ],
    )

    status = run_source_delivery_handoff(tmp_path)
    assert status["r4_9e_gate_passed"] is False
    assert status["r4_9e_retry_suppression_preserved"] is False
