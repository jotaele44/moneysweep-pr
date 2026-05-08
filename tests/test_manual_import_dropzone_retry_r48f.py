"""Tests for R4.8F manual import dropzone + retry orchestration."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from scripts.run_manual_import_dropzone_retry_r48f import run_manual_import_dropzone_retry


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
    _write_json(tmp_path / "data" / "exports" / "manual_fallback_package_r4_8e.json", {"sources": []})
    _write_csv(
        tmp_path / "data" / "exports" / "manual_fallback_inventory_r4_8e.csv",
        [],
        [
            "priority",
            "source_family",
            "expected_input",
            "required_file_type",
            "accepted_filename_patterns",
            "required_columns",
            "target_dropzone_path",
            "target_output_path",
            "validation_command",
            "source_url_or_portal",
            "manual_export_steps",
            "producer_script",
            "required_env_vars",
            "retry_status",
            "failure_reason",
            "next_action",
            "forbidden_artifact_usage",
        ],
    )

    manual_rows = [
        {
            "priority": "1",
            "source_family": "source_a",
            "expected_input": "data/staging/processed/source_a.csv",
            "required_file_type": "csv",
            "accepted_filename_patterns": "source_a.csv|source_a*.csv",
            "required_columns": "award_id|recipient_name",
            "target_dropzone_path": "data/manual_import_dropzone/r4_8e/source_a/source_a.csv",
            "target_output_path": "data/staging/processed/source_a.csv",
            "validation_command": "python -c \"print(1)\"",
            "source_url_or_portal": "https://example.test/a",
            "manual_export_steps": "step",
            "producer_script": "scripts/download_a.py",
            "required_env_vars": "",
            "retry_status": "failed_no_data",
            "failure_reason": "missing",
            "next_action": "require_manual_file",
            "manual_file_received": "False",
            "review_status": "pending_manual_file",
        },
        {
            "priority": "2",
            "source_family": "source_b",
            "expected_input": "data/staging/processed/source_b.csv",
            "required_file_type": "csv",
            "accepted_filename_patterns": "source_b.csv|source_b*.csv",
            "required_columns": "award_id|recipient_name",
            "target_dropzone_path": "data/manual_import_dropzone/r4_8e/source_b/source_b.csv",
            "target_output_path": "data/staging/processed/source_b.csv",
            "validation_command": "python -c \"print(1)\"",
            "source_url_or_portal": "https://example.test/b",
            "manual_export_steps": "step",
            "producer_script": "scripts/download_b.py",
            "required_env_vars": "",
            "retry_status": "failed_no_data",
            "failure_reason": "missing",
            "next_action": "require_manual_file",
            "manual_file_received": "False",
            "review_status": "pending_manual_file",
        },
    ]
    _write_csv(
        tmp_path / "data" / "review_queue" / "manual_files_required_r4_8e.csv",
        manual_rows,
        list(manual_rows[0].keys()),
    )

    # Source A manual dropzone file exists and should validate.
    dropzone_file = tmp_path / "data" / "manual_import_dropzone" / "r4_8e" / "source_a" / "source_a.csv"
    dropzone_file.parent.mkdir(parents=True, exist_ok=True)
    dropzone_file.write_text("award_id,recipient_name\n1,Alpha\n2,Beta\n", encoding="utf-8")

    endpoint_rows = [
        {
            "priority": "2",
            "expected_input": "data/staging/processed/source_b.csv",
            "source_family": "source_b",
            "producer_script": "scripts/download_unknown.py",
            "source_url_or_portal": "https://example.test/b",
            "failure_reason": "endpoint unavailable source left queued",
            "endpoint_classification": "endpoint_down",
            "next_action": "retry_endpoint_after_backoff",
            "probe_attempted": "False",
            "probe_ok": "False",
            "probe_status_code": "",
            "probe_error": "",
            "review_status": "pending_followup",
        }
    ]
    _write_csv(
        tmp_path / "data" / "review_queue" / "endpoint_followup_required_r4_8e.csv",
        endpoint_rows,
        list(endpoint_rows[0].keys()),
    )
    _write_csv(
        tmp_path / "data" / "exports" / "endpoint_resolution_report_r4_8e.csv",
        endpoint_rows,
        [key for key in endpoint_rows[0].keys() if key != "review_status"],
    )

    producer_rows = [
        {
            "priority": "2",
            "expected_input": "data/staging/processed/source_b.csv",
            "source_family": "source_b",
            "producer_script": "scripts/download_unknown.py",
            "retry_status": "failed_command",
            "failure_reason": "boom",
            "endpoint_classification": "",
            "producer_classification": "patchable_now",
            "next_action": "patch_producer_script",
            "recommended_patch": "safe patch",
            "review_status": "pending",
        }
    ]
    _write_csv(
        tmp_path / "data" / "review_queue" / "producer_patch_remaining_r4_8e.csv",
        producer_rows,
        list(producer_rows[0].keys()),
    )
    _write_csv(
        tmp_path / "data" / "exports" / "producer_failure_resolution_report_r4_8e.csv",
        producer_rows,
        [key for key in producer_rows[0].keys() if key != "review_status"],
    )

    _write_csv(
        tmp_path / "data" / "review_queue" / "backfill_retry_order_r4_8e.csv",
        [
            {
                "retry_rank": "1",
                "priority": "1",
                "expected_input": "data/staging/processed/source_a.csv",
                "source_family": "source_a",
                "endpoint_classification": "",
                "producer_classification": "requires_manual_source",
                "next_action": "require_manual_file",
            },
            {
                "retry_rank": "2",
                "priority": "2",
                "expected_input": "data/staging/processed/source_b.csv",
                "source_family": "source_b",
                "endpoint_classification": "endpoint_down",
                "producer_classification": "patchable_now",
                "next_action": "retry_endpoint_after_backoff",
            },
        ],
        [
            "retry_rank",
            "priority",
            "expected_input",
            "source_family",
            "endpoint_classification",
            "producer_classification",
            "next_action",
        ],
    )

    _write_csv(
        tmp_path / "data" / "exports" / "validated_source_manifest_inventory_r4_8d.csv",
        [
            {
                "source_system": "base_source",
                "source_file": "data/staging/processed/base.csv",
                "target_output_path": "data/staging/processed/base.csv",
                "row_count": "10",
                "sha256": "abc123",
                "generated_at": "2026-05-08T00:00:00Z",
                "producer_script": "scripts/download_base.py",
                "validation_status": "validated",
                "known_gaps": "",
                "schema_version": "r4_8d_schema_v1",
                "manifest_type": "validated_source_manifest",
                "manifest_path": "data/manifests/r4_8d/base.manifest.json",
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

    _write_json(
        tmp_path / "data" / "exports" / "targeted_backfill_retry_status_r4_8d.json",
        {
            "r4_8d_rows_ingested": 10,
            "r4_8d_production_inputs_staged": 1,
            "r4_8d_validated_source_manifests_written": 1,
            "phase_7_8_blocked": True,
            "row_fabrication_policy": "FORBIDDEN_NO_SYNTHETIC_ROWS",
        },
    )

    _write_json(
        tmp_path / "data" / "exports" / "rebuild_status.json",
        {
            "phase_7_8_blocked": True,
            "row_fabrication_policy": "FORBIDDEN_NO_SYNTHETIC_ROWS",
        },
    )


def test_r48f_runs_and_writes_outputs(tmp_path: Path):
    _bootstrap_inputs(tmp_path)

    result = run_manual_import_dropzone_retry(tmp_path)

    assert result["r4_8f_gate_passed"] is True
    assert result["r4_8f_manual_sources_checked"] == 2
    assert result["r4_8f_manual_files_found"] == 1
    assert result["r4_8f_manual_files_validated"] == 1
    assert result["r4_8f_manual_files_still_required"] == 1
    assert result["r4_8f_endpoint_followups_reviewed"] == 1
    assert result["r4_8f_endpoint_patches_applied"] == 0
    assert result["r4_8f_endpoint_retries_attempted"] == 0
    assert result["r4_8f_endpoint_retries_successful"] == 0
    assert result["r4_8f_producer_patches_applied"] == 0
    assert result["r4_8f_producer_retries_attempted"] == 0
    assert result["r4_8f_producer_retries_successful"] == 0
    assert result["r4_8f_new_rows_ingested"] == 2
    assert result["r4_8f_new_production_inputs_staged"] == 1
    assert result["r4_8f_new_validated_source_manifests"] == 1
    assert result["r4_8f_rows_ingested_total"] == 12
    assert result["r4_8f_production_inputs_staged_total"] == 2
    assert result["r4_8f_validated_source_manifests_total"] == 2
    assert result["r4_8f_forbidden_artifact_usage"] is False
    assert result["phase_7_8_blocked"] is True

    assert (tmp_path / "data" / "exports" / "manual_import_dropzone_status_r4_8f.json").exists()
    assert (tmp_path / "data" / "exports" / "manual_import_dropzone_inventory_r4_8f.csv").exists()
    assert (tmp_path / "data" / "exports" / "endpoint_patch_retry_report_r4_8f.csv").exists()
    assert (tmp_path / "data" / "exports" / "producer_patch_retry_report_r4_8f.csv").exists()
    assert (tmp_path / "data" / "exports" / "validated_source_manifest_inventory_r4_8f.csv").exists()
    assert (tmp_path / "data" / "review_queue" / "manual_files_still_required_r4_8f.csv").exists()
    assert (tmp_path / "data" / "review_queue" / "endpoint_failures_remaining_r4_8f.csv").exists()
    assert (tmp_path / "data" / "review_queue" / "producer_failures_remaining_r4_8f.csv").exists()
    assert (tmp_path / "data" / "review_queue" / "backfill_retry_order_r4_8f.csv").exists()


def test_r48f_blocks_forbidden_artifact_path(tmp_path: Path):
    _bootstrap_inputs(tmp_path)

    manual_path = tmp_path / "data" / "review_queue" / "manual_files_required_r4_8e.csv"
    rows = list(csv.DictReader(manual_path.open(encoding="utf-8")))
    rows[0]["expected_input"] = "data/staging/processed/investigative_report.csv"
    _write_csv(manual_path, rows, list(rows[0].keys()))

    result = run_manual_import_dropzone_retry(tmp_path)

    assert result["r4_8f_gate_passed"] is False
    assert result["r4_8f_forbidden_artifact_usage"] is True
