"""Tests for R4.9F source delivery watch and unfreeze guard."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from moneysweep.pipeline.source_delivery_watch import run_source_delivery_watch


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _csv_rows(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _bootstrap_base(tmp_path: Path, checklist_rows: list[dict]) -> None:
    (tmp_path / "docs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "docs" / "SOURCE_DELIVERY_HANDOFF_R4_9E.md").write_text(
        "# handoff",
        encoding="utf-8",
    )
    (tmp_path / "docs" / "EXTERNAL_BLOCKER_FREEZE_STATUS_R4_9E.md").write_text(
        "# freeze",
        encoding="utf-8",
    )

    _write_json(
        tmp_path / "data" / "exports" / "source_delivery_handoff_status_r4_9e.json",
        {
            "r4_9e_gate_passed": True,
            "r4_9e_delivery_checklist_count": len(checklist_rows),
            "r4_9e_unfreeze_trigger_count": len(checklist_rows),
            "production_status": "NON_PRODUCTION_DIAGNOSTIC",
            "phase_7_8_blocked": True,
        },
    )
    _write_csv(
        tmp_path / "data" / "review_queue" / "source_delivery_checklist_r4_9e.csv",
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
    _write_csv(
        tmp_path / "data" / "review_queue" / "unfreeze_trigger_conditions_r4_9e.csv",
        [
            {
                "expected_input": row["expected_input"],
                "source_family": row["source_family"],
                "blocker_class": row["blocker_class"],
                "trigger_file_delivered": "True",
                "trigger_schema_valid": "True",
                "trigger_nonzero_rows": "True",
                "trigger_sha256_computed": "True",
                "trigger_manifest_written": "True",
                "trigger_blocker_resolved": "True",
                "validation_command": row["validation_command"],
                "unfreeze_condition": row["unfreeze_condition"],
                "trigger_status": "pending_external_delivery",
            }
            for row in checklist_rows
        ],
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
    _write_csv(
        tmp_path / "data" / "review_queue" / "retry_suppression_queue_r4_9d.csv",
        [
            {
                "request_id": f"manual:{row['expected_input']}",
                "expected_input": row["expected_input"],
                "source_family": row["source_family"],
                "suppression_status": "suppressed",
                "suppression_reason": "external_source_unavailable_or_undelivered",
                "suppression_scope": "block_generic_retry_loop",
                "unsuppress_condition": row["unfreeze_condition"],
                "retry_allowed": "False",
            }
            for row in checklist_rows
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
                "blocker_reason": "blocked by external source delivery",
                "unfreeze_condition": "deliver and validate required sources",
                "status": "blocked",
            },
            {
                "phase_code": "R8_GRAPH_REBUILD",
                "blocked": "True",
                "blocker_reason": "blocked by external source delivery",
                "unfreeze_condition": "deliver and validate required sources",
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


def test_source_delivery_watch_passes_with_missing_sources_queued(tmp_path: Path):
    checklist_rows = [
        {
            "expected_input": "data/staging/processed/pr_contracts_master.csv",
            "source_family": "usaspending",
            "blocker_class": "manual_file_required",
            "target_dropzone_path": "data/manual_import_dropzone/r4_9e/usaspending/pr_contracts_master.csv",
            "target_output_path": "data/staging/processed/pr_contracts_master.csv",
            "accepted_filename_patterns": "pr_contracts_master.csv|*.csv",
            "required_columns": "award_id|recipient_name",
            "validation_command": "echo validate contracts",
            "unfreeze_condition": "deliver manual file and validate",
            "reason_blocked": "file_not_delivered",
        },
        {
            "expected_input": "data/staging/processed/pr_subawards_master.csv",
            "source_family": "fsrs",
            "blocker_class": "manual_file_required",
            "target_dropzone_path": "data/manual_import_dropzone/r4_9e/fsrs/pr_subawards_master.csv",
            "target_output_path": "data/staging/processed/pr_subawards_master.csv",
            "accepted_filename_patterns": "pr_subawards_master.csv|*.csv",
            "required_columns": "award_id|subaward_id",
            "validation_command": "echo validate subawards",
            "unfreeze_condition": "deliver manual file and validate",
            "reason_blocked": "file_not_delivered",
        },
    ]
    _bootstrap_base(tmp_path, checklist_rows)

    status = run_source_delivery_watch(tmp_path)
    assert status["r4_9f_gate_passed"] is True
    assert status["r4_9f_checklist_rows_checked"] == 2
    assert status["r4_9f_candidate_files_found"] == 0
    assert status["r4_9f_unfreeze_candidates"] == 0
    assert status["r4_9f_sources_still_missing"] == 2
    assert status["r4_9f_retry_suppression_preserved"] is True
    assert status["r4_9f_downstream_blockers_preserved"] is True
    assert status["r4_9f_downloads_executed"] is False
    assert status["r4_9f_rows_ingested"] == 0
    assert status["r4_9f_production_inputs_staged"] == 0
    assert status["r4_9f_forbidden_artifact_usage"] is False
    assert status["production_status"] == "NON_PRODUCTION_DIAGNOSTIC"
    assert status["phase_7_8_blocked"] is True

    missing_rows = _csv_rows(
        tmp_path / "data" / "review_queue" / "source_delivery_still_missing_r4_9f.csv"
    )
    assert len(missing_rows) == 2
    unfreeze_rows = _csv_rows(tmp_path / "data" / "review_queue" / "unfreeze_candidates_r4_9f.csv")
    assert len(unfreeze_rows) == 0


def test_source_delivery_watch_detects_unfreeze_candidate_without_materializing(tmp_path: Path):
    checklist_rows = [
        {
            "expected_input": "data/staging/processed/pr_contracts_master.csv",
            "source_family": "usaspending",
            "blocker_class": "manual_file_required",
            "target_dropzone_path": "data/manual_import_dropzone/r4_9e/usaspending/pr_contracts_master.csv",
            "target_output_path": "data/staging/processed/pr_contracts_master.csv",
            "accepted_filename_patterns": "pr_contracts_master.csv|*.csv",
            "required_columns": "award_id|recipient_name",
            "validation_command": "echo validate contracts",
            "unfreeze_condition": "deliver manual file and validate",
            "reason_blocked": "file_not_delivered",
        },
        {
            "expected_input": "data/staging/processed/pr_subawards_master.csv",
            "source_family": "fsrs",
            "blocker_class": "manual_file_required",
            "target_dropzone_path": "data/manual_import_dropzone/r4_9e/fsrs/pr_subawards_master.csv",
            "target_output_path": "data/staging/processed/pr_subawards_master.csv",
            "accepted_filename_patterns": "pr_subawards_master.csv|*.csv",
            "required_columns": "award_id|subaward_id",
            "validation_command": "echo validate subawards",
            "unfreeze_condition": "deliver manual file and validate",
            "reason_blocked": "file_not_delivered",
        },
    ]
    _bootstrap_base(tmp_path, checklist_rows)

    delivered = (
        tmp_path
        / "data"
        / "manual_import_dropzone"
        / "r4_9e"
        / "usaspending"
        / "pr_contracts_master.csv"
    )
    _write_csv(
        delivered,
        [{"award_id": "A-1", "recipient_name": "Utility"}],
        ["award_id", "recipient_name"],
    )

    status = run_source_delivery_watch(tmp_path)
    assert status["r4_9f_gate_passed"] is True
    assert status["r4_9f_checklist_rows_checked"] == 2
    assert status["r4_9f_candidate_files_found"] >= 1
    assert status["r4_9f_unfreeze_candidates"] == 1
    assert status["r4_9f_sources_still_missing"] == 1
    assert status["r4_9f_retry_suppression_preserved"] is True
    assert status["r4_9f_downstream_blockers_preserved"] is True
    assert status["r4_9f_downloads_executed"] is False
    assert status["r4_9f_rows_ingested"] == 0
    assert status["r4_9f_production_inputs_staged"] == 0
    assert status["r4_9f_forbidden_artifact_usage"] is False
    assert status["production_status"] == "NON_PRODUCTION_DIAGNOSTIC"
    assert status["phase_7_8_blocked"] is True

    unfreeze_rows = _csv_rows(tmp_path / "data" / "review_queue" / "unfreeze_candidates_r4_9f.csv")
    assert len(unfreeze_rows) == 1
    assert unfreeze_rows[0]["expected_input"] == "data/staging/processed/pr_contracts_master.csv"


def test_source_delivery_watch_blocks_forbidden_artifact_paths(tmp_path: Path):
    checklist_rows = [
        {
            "expected_input": "data/reports/pr_contracts_master.csv",
            "source_family": "usaspending",
            "blocker_class": "manual_file_required",
            "target_dropzone_path": "data/manual_import_dropzone/r4_9e/usaspending/pr_contracts_master.csv",
            "target_output_path": "data/reports/pr_contracts_master.csv",
            "accepted_filename_patterns": "pr_contracts_master.csv|*.csv",
            "required_columns": "award_id|recipient_name",
            "validation_command": "echo validate contracts",
            "unfreeze_condition": "deliver manual file and validate",
            "reason_blocked": "file_not_delivered",
        }
    ]
    _bootstrap_base(tmp_path, checklist_rows)

    status = run_source_delivery_watch(tmp_path)
    assert status["r4_9f_gate_passed"] is False
    assert status["r4_9f_forbidden_artifact_usage"] is True
