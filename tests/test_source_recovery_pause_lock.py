"""Tests for R4.9Z source recovery pause and status lock."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from moneysweep.pipeline.source_recovery_pause_lock import run_source_recovery_pause_lock


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


def _still_missing_rows(count: int) -> list[dict]:
    rows: list[dict] = []
    for idx in range(1, count + 1):
        rows.append(
            {
                "expected_input": f"data/staging/processed/source_{idx}.csv",
                "source_family": f"source_{idx}",
                "blocker_class": "manual_file_required",
                "target_dropzone_path": f"data/manual_import_dropzone/r4_9e/source_{idx}.csv",
                "target_output_path": f"data/staging/processed/source_{idx}.csv",
                "missing_reason": "source_file_not_found",
                "next_action": "await_external_source_delivery",
                "validation_command": f"echo validate source_{idx}",
                "unfreeze_condition": "deliver file + pass validation + resolve blocker",
            }
        )
    return rows


def _bootstrap(tmp_path: Path, *, missing_count: int, unfreeze_count: int) -> None:
    (tmp_path / "docs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "docs" / "SOURCE_DELIVERY_HANDOFF_R4_9E.md").write_text(
        "# handoff", encoding="utf-8"
    )
    (tmp_path / "docs" / "EXTERNAL_BLOCKER_FREEZE_STATUS_R4_9E.md").write_text(
        "# freeze",
        encoding="utf-8",
    )

    _write_json(
        tmp_path / "data" / "exports" / "source_delivery_watch_status_r4_9f.json",
        {
            "r4_9f_gate_passed": True,
            "r4_9f_checklist_rows_checked": 21,
            "r4_9f_candidate_files_found": 0,
            "r4_9f_unfreeze_candidates": unfreeze_count,
            "r4_9f_sources_still_missing": missing_count,
            "r4_9f_retry_suppression_preserved": True,
            "r4_9f_downstream_blockers_preserved": True,
            "r4_9f_downloads_executed": False,
            "r4_9f_rows_ingested": 0,
            "r4_9f_production_inputs_staged": 0,
            "r4_9f_forbidden_artifact_usage": False,
            "production_status": "NON_PRODUCTION_DIAGNOSTIC",
            "row_fabrication_policy": "FORBIDDEN_NO_SYNTHETIC_ROWS",
            "phase_7_8_blocked": True,
        },
    )
    _write_csv(
        tmp_path / "data" / "exports" / "source_delivery_watch_results_r4_9f.csv",
        [
            {
                "generated_at": "2026-05-09T00:00:00Z",
                "expected_input": row["expected_input"],
                "source_family": row["source_family"],
                "blocker_class": row["blocker_class"],
                "candidate_path": "",
                "candidate_relpath": "",
                "candidate_filename": "",
                "candidate_found": "False",
                "candidate_valid": "False",
                "candidate_row_count": "0",
                "candidate_sha256": "",
                "validation_result": "missing",
                "validation_reason": "source_file_not_found",
                "watch_status": "still_missing",
                "unfreeze_candidate": "False",
            }
            for row in _still_missing_rows(missing_count)
        ],
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

    _write_csv(
        tmp_path / "data" / "review_queue" / "unfreeze_candidates_r4_9f.csv",
        [
            {
                "expected_input": f"data/staging/processed/unfreeze_{idx}.csv",
                "source_family": f"source_{idx}",
                "blocker_class": "manual_file_required",
                "candidate_path": f"data/manual_import_dropzone/r4_9e/unfreeze_{idx}.csv",
                "candidate_relpath": f"data/manual_import_dropzone/r4_9e/unfreeze_{idx}.csv",
                "candidate_filename": f"unfreeze_{idx}.csv",
                "candidate_row_count": "10",
                "candidate_sha256": "abc",
                "validation_command": "echo validate",
                "unfreeze_condition": "deliver file + pass validation + resolve blocker",
            }
            for idx in range(1, unfreeze_count + 1)
        ],
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

    _write_csv(
        tmp_path / "data" / "review_queue" / "source_delivery_still_missing_r4_9f.csv",
        _still_missing_rows(missing_count),
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
    _write_csv(
        tmp_path / "data" / "review_queue" / "downstream_phase_blockers_r4_9f.csv",
        [
            {
                "generated_at": "2026-05-09T00:00:00Z",
                "phase_code": "R5_ENTITY_RESOLUTION",
                "blocked": "True",
                "blocker_reason": "blocked by external source delivery",
                "unfreeze_condition": "deliver and validate required sources",
                "status": "blocked",
            },
            {
                "generated_at": "2026-05-09T00:00:00Z",
                "phase_code": "R6_EXECUTION_CHAIN_REBUILD",
                "blocked": "True",
                "blocker_reason": "blocked by external source delivery",
                "unfreeze_condition": "deliver and validate required sources",
                "status": "blocked",
            },
        ],
        ["generated_at", "phase_code", "blocked", "blocker_reason", "unfreeze_condition", "status"],
    )
    _write_json(
        tmp_path / "data" / "exports" / "rebuild_status.json",
        {
            "production_status": "NON_PRODUCTION_DIAGNOSTIC",
            "row_fabrication_policy": "FORBIDDEN_NO_SYNTHETIC_ROWS",
            "phase_7_8_blocked": True,
        },
    )


def test_source_recovery_pause_lock_passes(tmp_path: Path):
    _bootstrap(tmp_path, missing_count=21, unfreeze_count=0)
    status = run_source_recovery_pause_lock(tmp_path)

    assert status["r4_9z_gate_passed"] is True
    assert status["r4_9z_pause_lock_active"] is True
    assert status["r4_9z_unfreeze_candidates"] == 0
    assert status["r4_9z_sources_still_missing"] == 21
    assert status["r4_9z_retry_suppression_active"] is True
    assert status["r4_9z_downstream_blockers_active"] is True
    assert status["r4_9z_downloads_executed"] is False
    assert status["r4_9z_rows_ingested"] == 0
    assert status["r4_9z_production_inputs_staged"] == 0
    assert status["r4_9z_forbidden_artifact_usage"] is False
    assert status["production_status"] == "NON_PRODUCTION_DIAGNOSTIC"
    assert status["phase_7_8_blocked"] is True

    pause_matrix = _csv_rows(
        tmp_path / "data" / "exports" / "source_recovery_pause_matrix_r4_9z.csv"
    )
    assert len(pause_matrix) == 21
    resume_rows = _csv_rows(
        tmp_path / "data" / "review_queue" / "source_recovery_resume_conditions_r4_9z.csv"
    )
    assert len(resume_rows) == 21
    blockers_rows = _csv_rows(
        tmp_path / "data" / "review_queue" / "downstream_phase_blockers_r4_9z.csv"
    )
    assert len(blockers_rows) == 2

    assert (tmp_path / "docs" / "SOURCE_RECOVERY_PAUSE_STATUS_R4_9Z.md").exists()


def test_source_recovery_pause_lock_fails_on_count_mismatch(tmp_path: Path):
    _bootstrap(tmp_path, missing_count=20, unfreeze_count=1)
    status = run_source_recovery_pause_lock(tmp_path)

    assert status["r4_9z_gate_passed"] is False
    assert status["r4_9z_pause_lock_active"] is False
    assert status["r4_9z_unfreeze_candidates"] == 1
    assert status["r4_9z_sources_still_missing"] == 20
