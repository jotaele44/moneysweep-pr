"""Tests for R4.9D external blocker freeze and completion gate."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from moneysweep.pipeline.external_blocker_freeze import run_external_blocker_freeze


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _bootstrap(tmp_path: Path) -> None:
    _write_json(
        tmp_path / "data" / "exports" / "external_source_delivery_status_r4_9c.json",
        {
            "r4_9c_gate_passed": True,
            "r4_9c_delivery_requests_checked": 2,
            "r4_9c_delivery_blockers": 2,
            "production_status": "NON_PRODUCTION_DIAGNOSTIC",
            "phase_7_8_blocked": True,
        },
    )
    _write_csv(
        tmp_path / "data" / "exports" / "external_source_delivery_results_r4_9c.csv",
        [],
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
    _write_csv(
        tmp_path / "data" / "exports" / "delivered_source_validation_report_r4_9c.csv",
        [],
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
    _write_csv(
        tmp_path / "data" / "exports" / "validated_source_manifest_inventory_r4_9c.csv",
        [
            {
                "source_system": "federal_sectoral_doe",
                "source_file": "data/staging/processed/pr_doe_master.csv",
                "target_output_path": "data/staging/processed/pr_doe_master.csv",
                "row_count": "180",
                "sha256": "abc123",
                "generated_at": "2026-05-09T00:00:00Z",
                "producer_script": "scripts/download_doe.py",
                "validation_status": "validated",
                "known_gaps": "",
                "schema_version": "r4_9c_schema_v1",
                "manifest_type": "validated_source_manifest",
                "manifest_path": "data/manifests/r4_8d/12_pr_doe_master.manifest.json",
            }
        ],
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

    blockers = [
        {
            "request_id": "manual:data/staging/processed/pr_contracts_master.csv",
            "request_type": "manual_file_delivery",
            "source_family": "usaspending_federal_awards_backbone",
            "expected_input": "data/staging/processed/pr_contracts_master.csv",
            "target_output_path": "data/staging/processed/pr_contracts_master.csv",
            "blocker_reason": "file_not_delivered",
            "next_action": "manual_source_delivery",
        },
        {
            "request_id": "validated:data/staging/processed/pr_doe_master.csv",
            "request_type": "validated_manifest_delivery",
            "source_family": "federal_sectoral_doe",
            "expected_input": "data/staging/processed/pr_doe_master.csv",
            "target_output_path": "data/staging/processed/pr_doe_master.csv",
            "blocker_reason": "file_not_delivered",
            "next_action": "physical_validated_source_delivery",
        },
    ]
    _write_csv(
        tmp_path / "data" / "review_queue" / "external_source_delivery_blockers_r4_9c.csv",
        blockers,
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
    _write_csv(
        tmp_path / "data" / "review_queue" / "manual_files_still_required_r4_9c.csv",
        [
            {
                "priority": "1",
                "source_family": "usaspending_federal_awards_backbone",
                "expected_input": "data/staging/processed/pr_contracts_master.csv",
                "target_dropzone_path": "data/manual_import_dropzone/r4_8e/usaspending/pr_contracts_master.csv",
                "target_output_path": "data/staging/processed/pr_contracts_master.csv",
                "accepted_filename_patterns": "pr_contracts_master.csv|*.csv",
                "required_columns": "contract_id|vendor_name|agency_name",
                "source_url_or_portal": "https://api.usaspending.gov",
                "failure_reason": "file_not_delivered",
                "review_status": "pending_manual_file",
            }
        ],
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
    _write_csv(
        tmp_path / "data" / "review_queue" / "physical_validated_files_still_missing_r4_9c.csv",
        [
            {
                "request_id": "validated:data/staging/processed/pr_doe_master.csv",
                "source_family": "federal_sectoral_doe",
                "expected_input": "data/staging/processed/pr_doe_master.csv",
                "target_output_path": "data/staging/processed/pr_doe_master.csv",
                "manifest_path": "data/manifests/r4_8d/12_pr_doe_master.manifest.json",
                "failure_reason": "file_not_delivered",
                "review_status": "pending_physical_delivery",
            }
        ],
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
    _write_csv(
        tmp_path / "data" / "review_queue" / "backfill_retry_order_r4_9c.csv",
        [
            {
                "retry_rank": "1",
                "priority": "1",
                "expected_input": "data/staging/processed/pr_contracts_master.csv",
                "source_family": "usaspending_federal_awards_backbone",
                "next_action": "manual_source_delivery",
                "reason": "file_not_delivered",
            },
            {
                "retry_rank": "2",
                "priority": "1",
                "expected_input": "data/staging/processed/pr_doe_master.csv",
                "source_family": "federal_sectoral_doe",
                "next_action": "physical_validated_source_delivery",
                "reason": "file_not_delivered",
            },
        ],
        ["retry_rank", "priority", "expected_input", "source_family", "next_action", "reason"],
    )

    # Optional richer validation command lookup source.
    _write_csv(
        tmp_path / "data" / "review_queue" / "manual_files_still_required_r4_8i.csv",
        [
            {
                "priority": "1",
                "source_family": "usaspending_federal_awards_backbone",
                "expected_input": "data/staging/processed/pr_contracts_master.csv",
                "target_dropzone_path": "data/manual_import_dropzone/r4_8e/usaspending/pr_contracts_master.csv",
                "target_output_path": "data/staging/processed/pr_contracts_master.csv",
                "accepted_filename_patterns": "pr_contracts_master.csv|*.csv",
                "required_columns": "contract_id|vendor_name|agency_name",
                "validation_command": "python -c \"print('validate contracts')\"",
                "source_url_or_portal": "https://api.usaspending.gov",
                "producer_script": "",
                "manual_file_received": "False",
                "review_status": "pending_manual_file",
                "failure_reason": "no_file_present",
            }
        ],
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

    _write_json(
        tmp_path / "data" / "exports" / "rebuild_status.json",
        {
            "production_status": "NON_PRODUCTION_DIAGNOSTIC",
            "row_fabrication_policy": "FORBIDDEN_NO_SYNTHETIC_ROWS",
            "phase_7_8_blocked": True,
        },
    )


def _load_csv_rows(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def test_external_blocker_freeze_gate_passes(tmp_path: Path):
    _bootstrap(tmp_path)
    status = run_external_blocker_freeze(tmp_path)

    assert status["r4_9d_gate_passed"] is True
    assert status["r4_9d_blockers_frozen"] == 2
    assert status["r4_9d_manual_file_required"] == 1
    assert status["r4_9d_physical_validated_file_missing"] == 1
    assert status["r4_9d_retry_suppressed"] == 2
    assert status["r4_9d_downstream_phases_blocked"] == 7
    assert status["r4_9d_unfreeze_requirements_written"] is True
    assert status["r4_9d_downloads_executed"] is False
    assert status["r4_9d_rows_ingested"] == 0
    assert status["r4_9d_production_inputs_staged"] == 0
    assert status["r4_9d_forbidden_artifact_usage"] is False
    assert status["production_status"] == "NON_PRODUCTION_DIAGNOSTIC"
    assert status["phase_7_8_blocked"] is True

    freeze_rows = _load_csv_rows(
        tmp_path / "data" / "exports" / "external_blocker_freeze_matrix_r4_9d.csv"
    )
    assert len(freeze_rows) == 2
    assert {row["blocker_class"] for row in freeze_rows} == {
        "manual_file_required",
        "physical_validated_file_missing",
    }
    assert all(row["unfreeze_condition"] for row in freeze_rows)


def test_external_blocker_freeze_forbidden_artifact_blocks_gate(tmp_path: Path):
    _bootstrap(tmp_path)
    blockers_path = (
        tmp_path / "data" / "review_queue" / "external_source_delivery_blockers_r4_9c.csv"
    )
    rows = _load_csv_rows(blockers_path)
    rows[0]["expected_input"] = "data/reports/investigative_report.csv"
    rows[0]["target_output_path"] = "data/reports/investigative_report.csv"
    _write_csv(
        blockers_path,
        rows,
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

    status = run_external_blocker_freeze(tmp_path)
    assert status["r4_9d_gate_passed"] is False
    assert status["r4_9d_forbidden_artifact_usage"] is True
