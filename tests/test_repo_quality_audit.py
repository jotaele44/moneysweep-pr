"""Tests for R4.9Z-B repository quality and CI hardening audit."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from moneysweep.pipeline.repo_quality_audit import run_repo_quality_audit


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _bootstrap(tmp_path: Path, *, forbidden_in_resume: bool) -> None:
    (tmp_path / "docs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "docs" / "OPERATOR_NEXT_ACTIONS_AFTER_R4_9Z.md").write_text(
        "# operator", encoding="utf-8"
    )
    (tmp_path / "docs" / "SOURCE_RECOVERY_PAUSE_STATUS_R4_9Z.md").write_text(
        "# pause", encoding="utf-8"
    )
    (tmp_path / "docs" / "SOURCE_DELIVERY_HANDOFF_R4_9E.md").write_text(
        "# handoff", encoding="utf-8"
    )
    (tmp_path / "docs" / "EXTERNAL_BLOCKER_FREEZE_STATUS_R4_9E.md").write_text(
        "# freeze", encoding="utf-8"
    )

    _write_json(
        tmp_path / "data" / "exports" / "post_pause_hygiene_status_r4_9z_a.json",
        {
            "r4_9z_a_gate_passed": True,
            "production_status": "NON_PRODUCTION_DIAGNOSTIC",
            "phase_7_8_blocked": True,
            "r4_9z_a_retry_suppression_active": True,
            "r4_9z_a_downstream_blockers_active": True,
        },
    )
    _write_json(
        tmp_path / "data" / "exports" / "source_recovery_pause_status_r4_9z.json",
        {
            "r4_9z_gate_passed": True,
            "r4_9z_pause_lock_active": True,
            "r4_9z_unfreeze_candidates": 0,
            "r4_9z_sources_still_missing": 21,
            "r4_9z_retry_suppression_active": True,
            "r4_9z_downstream_blockers_active": True,
        },
    )
    _write_json(
        tmp_path / "data" / "exports" / "rebuild_status.json",
        {
            "production_status": "NON_PRODUCTION_DIAGNOSTIC",
            "row_fabrication_policy": "FORBIDDEN_NO_SYNTHETIC_ROWS",
            "phase_7_8_blocked": True,
            "r4_9z_pause_lock_active": True,
            "r4_9z_unfreeze_candidates": 0,
            "r4_9z_sources_still_missing": 21,
            "r4_9z_retry_suppression_active": True,
            "r4_9z_downstream_blockers_active": True,
            "r4_7_gate_passed": True,
            "r4_8_gate_passed": True,
            "r4_8a_gate_passed": True,
            "r4_8b_gate_passed": True,
            "r4_8c_gate_passed": True,
            "r4_8d_gate_passed": True,
            "r4_8e_gate_passed": True,
            "r4_8f_gate_passed": True,
            "r4_8g_gate_passed": True,
            "r4_8h_gate_passed": True,
            "r4_8i_gate_passed": True,
            "r4_9a_gate_passed": True,
            "r4_9b_gate_passed": True,
            "r4_9c_gate_passed": True,
            "r4_9d_gate_passed": True,
            "r4_9e_gate_passed": True,
            "r4_9f_gate_passed": True,
            "r4_9z_gate_passed": True,
        },
    )

    expected_template = (
        "data/reports/investigative_source.csv"
        if forbidden_in_resume
        else "data/staging/processed/source_{idx}.csv"
    )
    output_template = (
        "data/reports/investigative_source.csv"
        if forbidden_in_resume
        else "data/staging/processed/source_{idx}.csv"
    )
    resume_rows = []
    for idx in range(1, 22):
        resume_rows.append(
            {
                "expected_input": expected_template.format(idx=idx),
                "source_family": f"source_{idx}",
                "blocker_class": "manual_file_required",
                "target_dropzone_path": f"data/manual_import_dropzone/source_{idx}.csv",
                "target_output_path": output_template.format(idx=idx),
                "required_delivery": "file_delivered",
                "required_schema_check": "required_columns_present",
                "required_row_check": "nonzero_rows",
                "required_hash_check": "sha256_computed",
                "required_manifest_check": "validated_manifest_written",
                "validation_command": f"echo validate source_{idx}",
                "resume_condition": "deliver file + pass validation + resolve blocker",
            }
        )
    _write_csv(
        tmp_path / "data" / "review_queue" / "source_recovery_resume_conditions_r4_9z.csv",
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

    _write_csv(
        tmp_path / "data" / "review_queue" / "retry_suppression_queue_r4_9d.csv",
        [
            {
                "request_id": f"manual:{idx}",
                "expected_input": f"data/staging/processed/source_{idx}.csv",
                "source_family": f"source_{idx}",
                "suppression_status": "suppressed",
                "suppression_reason": "external_source_unavailable_or_undelivered",
                "suppression_scope": "block_generic_retry_loop",
                "unsuppress_condition": "deliver file + pass validation",
                "retry_allowed": "False",
            }
            for idx in range(1, 22)
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
        tmp_path / "data" / "review_queue" / "downstream_phase_blockers_r4_9z.csv",
        [
            {
                "generated_at": "2026-05-09T00:00:00Z",
                "phase_code": "R5_ENTITY_RESOLUTION",
                "blocked": "True",
                "blocker_reason": "blocked",
                "unfreeze_condition": "clear blockers",
                "status": "blocked",
                "pause_lock_active": "True",
            },
            {
                "generated_at": "2026-05-09T00:00:00Z",
                "phase_code": "R6_EXECUTION_CHAIN_REBUILD",
                "blocked": "True",
                "blocker_reason": "blocked",
                "unfreeze_condition": "clear blockers",
                "status": "blocked",
                "pause_lock_active": "True",
            },
            {
                "generated_at": "2026-05-09T00:00:00Z",
                "phase_code": "R7_FINANCIAL_INTEGRATION",
                "blocked": "True",
                "blocker_reason": "blocked",
                "unfreeze_condition": "clear blockers",
                "status": "blocked",
                "pause_lock_active": "True",
            },
            {
                "generated_at": "2026-05-09T00:00:00Z",
                "phase_code": "R8_GRAPH_REBUILD",
                "blocked": "True",
                "blocker_reason": "blocked",
                "unfreeze_condition": "clear blockers",
                "status": "blocked",
                "pause_lock_active": "True",
            },
        ],
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


def test_r49z_b_gate_passes(tmp_path: Path) -> None:
    _bootstrap(tmp_path, forbidden_in_resume=False)
    status = run_repo_quality_audit(tmp_path)

    assert status["r4_9z_b_gate_passed"] is True
    assert status["production_status"] == "NON_PRODUCTION_DIAGNOSTIC"
    assert status["phase_7_8_blocked"] is True
    assert status["retry_suppression_active"] is True
    assert status["downstream_blockers_active"] is True
    assert status["downloads_executed"] is False
    assert status["rows_ingested"] == 0
    assert status["production_inputs_staged"] == 0
    assert status["forbidden_artifact_usage"] is False

    assert (tmp_path / "docs" / "REPO_QUALITY_STATUS_AFTER_R4_9Z.md").exists()
    assert (tmp_path / "docs" / "CI_TESTING_STRATEGY.md").exists()


def test_r49z_b_gate_fails_with_forbidden_artifact_paths(tmp_path: Path) -> None:
    _bootstrap(tmp_path, forbidden_in_resume=True)
    status = run_repo_quality_audit(tmp_path)

    assert status["r4_9z_b_gate_passed"] is False
    assert status["forbidden_artifact_usage"] is True
