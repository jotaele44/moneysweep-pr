"""Tests for R4.8G acquisition and credential-unblock packaging."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from scripts.run_acquisition_package_r48g import run_acquisition_package


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _bootstrap_inputs(tmp_path: Path) -> None:
    _write_json(
        tmp_path / "data" / "exports" / "manual_import_dropzone_status_r4_8f.json",
        {
            "r4_8f_gate_passed": True,
            "r4_8f_rows_ingested_total": 3135,
            "r4_8f_production_inputs_staged_total": 7,
            "r4_8f_validated_source_manifests_total": 7,
            "r4_8f_manual_files_still_required": 2,
            "r4_8f_endpoint_retries_successful": 0,
            "r4_8f_producer_retries_successful": 0,
            "r4_8f_new_rows_ingested": 0,
            "r4_8f_new_production_inputs_staged": 0,
            "r4_8f_new_validated_source_manifests": 0,
            "r4_8f_forbidden_artifact_usage": False,
            "phase_7_8_blocked": True,
            "row_fabrication_policy": "FORBIDDEN_NO_SYNTHETIC_ROWS",
        },
    )

    _write_csv(
        tmp_path / "data" / "exports" / "manual_import_dropzone_inventory_r4_8f.csv",
        [
            {
                "priority": "1",
                "source_family": "source_a",
                "expected_input": "data/staging/processed/source_a.csv",
                "target_dropzone_path": "data/manual_import_dropzone/r4_8e/source_a/source_a.csv",
                "target_output_path": "data/staging/processed/source_a.csv",
                "accepted_filename_patterns": "source_a.csv|source_a*.csv",
                "required_columns": "award_id|recipient_name",
                "manual_file_found": "False",
                "manual_file_validated": "False",
                "selected_dropzone_file": "",
                "selected_dropzone_sha256": "",
                "selected_dropzone_rows": "0",
                "staged_output_sha256": "",
                "staged_output_rows": "0",
                "manifest_written": "False",
                "review_status": "pending_manual_file",
                "failure_reason": "no_file_present",
                "validation_command": "python -c \"print(1)\"",
                "source_url_or_portal": "https://example.test/a",
                "producer_script": "scripts/download_a.py",
                "forbidden_artifact_usage": "False",
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

    endpoint_rows = [
        {
            "priority": "2",
            "expected_input": "data/staging/processed/source_b.csv",
            "source_family": "source_b",
            "producer_script": "scripts/download_grants.py",
            "endpoint_classification": "endpoint_down",
            "next_action": "retry_endpoint_after_backoff",
            "source_url_or_portal": "https://api.usaspending.gov",
            "target_output_path": "data/staging/processed/source_b.csv",
            "deterministic_patch_applied": "True",
            "retry_attempted": "True",
            "retry_status": "failed_command",
            "retry_command": "python scripts/download_grants.py --force",
            "command_exit_code": "124",
            "command_excerpt_safe": "timeout",
            "row_count": "0",
            "sha256": "",
            "manifest_written": "False",
            "failure_reason": "command timed out after 30s",
        }
    ]
    _write_csv(
        tmp_path / "data" / "exports" / "endpoint_patch_retry_report_r4_8f.csv",
        endpoint_rows,
        list(endpoint_rows[0].keys()),
    )

    producer_rows = [
        {
            "priority": "3",
            "expected_input": "data/staging/processed/source_c.csv",
            "source_family": "source_c",
            "producer_script": "scripts/download_subawards.py",
            "producer_classification": "patchable_now",
            "next_action": "patch_producer_script",
            "target_output_path": "data/staging/processed/source_c.csv",
            "deterministic_patch_applied": "True",
            "retry_attempted": "True",
            "retry_status": "failed_command",
            "retry_command": "python scripts/download_subawards.py --force --allow-empty-success",
            "command_exit_code": "1",
            "command_excerpt_safe": "failure",
            "row_count": "0",
            "sha256": "",
            "manifest_written": "False",
            "failure_reason": "upstream endpoint failure",
        }
    ]
    _write_csv(
        tmp_path / "data" / "exports" / "producer_patch_retry_report_r4_8f.csv",
        producer_rows,
        list(producer_rows[0].keys()),
    )

    _write_csv(
        tmp_path / "data" / "exports" / "validated_source_manifest_inventory_r4_8f.csv",
        [
            {
                "source_system": "base",
                "source_file": "data/staging/processed/base.csv",
                "target_output_path": "data/staging/processed/base.csv",
                "row_count": "10",
                "sha256": "abc123",
                "generated_at": "2026-05-08T00:00:00Z",
                "producer_script": "scripts/download_base.py",
                "validation_status": "validated",
                "known_gaps": "",
                "schema_version": "r4_8f_schema_v1",
                "manifest_type": "validated_source_manifest",
                "manifest_path": "data/manifests/r4_8f/base.manifest.json",
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

    manual_required_rows = [
        {
            "priority": "1",
            "source_family": "source_a",
            "expected_input": "data/staging/processed/source_a.csv",
            "target_dropzone_path": "data/manual_import_dropzone/r4_8e/source_a/source_a.csv",
            "target_output_path": "data/staging/processed/source_a.csv",
            "accepted_filename_patterns": "source_a.csv|source_a*.csv",
            "required_columns": "award_id|recipient_name",
            "validation_command": "python -c \"print(1)\"",
            "source_url_or_portal": "https://example.test/a",
            "producer_script": "scripts/download_a.py",
            "manual_file_received": "False",
            "review_status": "pending_manual_file",
            "failure_reason": "no_file_present",
        },
        {
            "priority": "2",
            "source_family": "source_b",
            "expected_input": "data/staging/processed/source_b.csv",
            "target_dropzone_path": "data/manual_import_dropzone/r4_8e/source_b/source_b.csv",
            "target_output_path": "data/staging/processed/source_b.csv",
            "accepted_filename_patterns": "source_b.csv|source_b*.csv",
            "required_columns": "award_id|recipient_name",
            "validation_command": "python -c \"print(1)\"",
            "source_url_or_portal": "https://example.test/b",
            "producer_script": "scripts/download_grants.py",
            "manual_file_received": "False",
            "review_status": "pending_manual_file",
            "failure_reason": "no_file_present",
        },
    ]
    _write_csv(
        tmp_path / "data" / "review_queue" / "manual_files_still_required_r4_8f.csv",
        manual_required_rows,
        list(manual_required_rows[0].keys()),
    )

    _write_csv(
        tmp_path / "data" / "review_queue" / "endpoint_failures_remaining_r4_8f.csv",
        [
            {
                "priority": "2",
                "expected_input": "data/staging/processed/source_b.csv",
                "source_family": "source_b",
                "producer_script": "scripts/download_grants.py",
                "endpoint_classification": "endpoint_down",
                "next_action": "retry_endpoint_after_backoff",
                "target_output_path": "data/staging/processed/source_b.csv",
                "retry_status": "failed_command",
                "failure_reason": "command timed out after 30s",
                "review_status": "pending",
            }
        ],
        [
            "priority",
            "expected_input",
            "source_family",
            "producer_script",
            "endpoint_classification",
            "next_action",
            "target_output_path",
            "retry_status",
            "failure_reason",
            "review_status",
        ],
    )

    _write_csv(
        tmp_path / "data" / "review_queue" / "producer_failures_remaining_r4_8f.csv",
        [
            {
                "priority": "3",
                "expected_input": "data/staging/processed/source_c.csv",
                "source_family": "source_c",
                "producer_script": "scripts/download_subawards.py",
                "producer_classification": "patchable_now",
                "next_action": "patch_producer_script",
                "target_output_path": "data/staging/processed/source_c.csv",
                "retry_status": "failed_command",
                "failure_reason": "upstream endpoint failure",
                "review_status": "pending",
            }
        ],
        [
            "priority",
            "expected_input",
            "source_family",
            "producer_script",
            "producer_classification",
            "next_action",
            "target_output_path",
            "retry_status",
            "failure_reason",
            "review_status",
        ],
    )

    _write_csv(
        tmp_path / "data" / "review_queue" / "backfill_retry_order_r4_8f.csv",
        [
            {
                "retry_rank": "1",
                "priority": "1",
                "expected_input": "data/staging/processed/source_a.csv",
                "source_family": "source_a",
                "next_action": "require_manual_file",
                "reason": "no_file_present",
            },
            {
                "retry_rank": "2",
                "priority": "2",
                "expected_input": "data/staging/processed/source_b.csv",
                "source_family": "source_b",
                "next_action": "require_manual_file",
                "reason": "no_file_present",
            },
        ],
        ["retry_rank", "priority", "expected_input", "source_family", "next_action", "reason"],
    )

    _write_json(
        tmp_path / "data" / "exports" / "rebuild_status.json",
        {
            "phase_7_8_blocked": True,
            "row_fabrication_policy": "FORBIDDEN_NO_SYNTHETIC_ROWS",
        },
    )


def test_r48g_builds_package_and_passes_gate(tmp_path: Path):
    _bootstrap_inputs(tmp_path)

    result = run_acquisition_package(tmp_path)

    assert result["r4_8g_gate_passed"] is True
    assert result["r4_8g_manual_file_requests"] == 2
    assert result["r4_8g_credential_requests"] == 1
    assert result["r4_8g_endpoint_resolution_requests"] == 1
    assert result["r4_8g_producer_patch_requests"] == 1
    assert result["r4_8g_rows_ingested_total"] == 3135
    assert result["r4_8g_production_inputs_staged_total"] == 7
    assert result["r4_8g_validated_source_manifests_total"] == 7
    assert result["r4_8g_new_rows_ingested"] == 0
    assert result["r4_8g_new_production_inputs_staged"] == 0
    assert result["r4_8g_new_validated_source_manifests"] == 0
    assert result["r4_8g_forbidden_artifact_usage"] is False
    assert result["phase_7_8_blocked"] is True

    assert (tmp_path / "data" / "exports" / "acquisition_package_r4_8g.json").exists()
    assert (tmp_path / "data" / "exports" / "acquisition_package_r4_8g.md").exists()
    assert (tmp_path / "data" / "exports" / "credential_unblock_plan_r4_8g.csv").exists()
    assert (tmp_path / "data" / "exports" / "manual_file_acquisition_matrix_r4_8g.csv").exists()
    assert (tmp_path / "data" / "review_queue" / "manual_file_requests_r4_8g.csv").exists()
    assert (tmp_path / "data" / "review_queue" / "credential_requests_r4_8g.csv").exists()
    assert (tmp_path / "data" / "review_queue" / "endpoint_resolution_requests_r4_8g.csv").exists()
    assert (tmp_path / "data" / "review_queue" / "producer_patch_requests_r4_8g.csv").exists()
    assert (tmp_path / "data" / "review_queue" / "backfill_retry_order_r4_8g.csv").exists()


def test_r48g_rejects_forbidden_artifact_path(tmp_path: Path):
    _bootstrap_inputs(tmp_path)

    path = tmp_path / "data" / "review_queue" / "manual_files_still_required_r4_8f.csv"
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    rows[0]["expected_input"] = "data/staging/processed/investigative_report.csv"
    _write_csv(path, rows, list(rows[0].keys()))

    result = run_acquisition_package(tmp_path)

    assert result["r4_8g_gate_passed"] is False
    assert result["r4_8g_forbidden_artifact_usage"] is True
