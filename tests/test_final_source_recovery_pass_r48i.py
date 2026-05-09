"""Tests for R4.8I final source recovery pass."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from contract_sweeper.pipeline.final_source_recovery_pass import run_final_source_recovery_pass


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
        tmp_path / "data" / "exports" / "manual_fulfillment_endpoint_retry_status_r4_8h.json",
        {
            "r4_8h_gate_passed": True,
            "r4_8h_manual_files_still_required": 2,
            "r4_8h_endpoint_retries_attempted": 1,
            "r4_8h_producer_retries_attempted": 1,
            "r4_8h_rows_ingested_total": 10,
            "r4_8h_production_inputs_staged_total": 1,
            "r4_8h_validated_source_manifests_total": 1,
            "r4_8h_new_rows_ingested": 0,
            "r4_8h_new_production_inputs_staged": 0,
            "r4_8h_new_validated_source_manifests": 0,
            "r4_8h_forbidden_artifact_usage": False,
            "phase_7_8_blocked": True,
            "row_fabrication_policy": "FORBIDDEN_NO_SYNTHETIC_ROWS",
        },
    )

    # Required but not deeply used by the orchestrator.
    _write_csv(
        tmp_path / "data" / "exports" / "manual_fulfillment_results_r4_8h.csv",
        [],
        ["priority", "expected_input"],
    )
    _write_csv(
        tmp_path / "data" / "exports" / "credentialed_endpoint_retry_results_r4_8h.csv",
        [],
        ["priority", "expected_input"],
    )
    _write_csv(
        tmp_path / "data" / "exports" / "final_backfill_retry_results_r4_8h.csv",
        [],
        ["priority", "expected_input"],
    )

    _write_csv(
        tmp_path / "data" / "exports" / "validated_source_manifest_inventory_r4_8h.csv",
        [
            {
                "source_system": "base",
                "source_file": "data/staging/processed/base.csv",
                "target_output_path": "data/staging/processed/base.csv",
                "row_count": "10",
                "sha256": "abc123",
                "generated_at": "2026-05-09T00:00:00Z",
                "producer_script": "scripts/download_base.py",
                "validation_status": "validated",
                "known_gaps": "",
                "schema_version": "r4_8h_schema_v1",
                "manifest_type": "validated_source_manifest",
                "manifest_path": "data/manifests/r4_8h/base.manifest.json",
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

    manual_rows = [
        {
            "priority": "1",
            "source_family": "source_a",
            "expected_input": "data/staging/processed/source_a.csv",
            "target_dropzone_path": "data/manual_import_dropzone/r4_8e/source_a/source_a.csv",
            "target_output_path": "data/staging/processed/source_a.csv",
            "accepted_filename_patterns": "source_a.csv|source_a*.csv",
            "required_columns": "award_id|recipient_name",
            "validation_command": "python -c \"print('ok')\"",
            "source_url_or_portal": "https://example.test/a",
            "producer_script": "",
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
            "validation_command": "python -c \"print('ok')\"",
            "source_url_or_portal": "https://example.test/b",
            "producer_script": "",
            "manual_file_received": "False",
            "review_status": "pending_manual_file",
            "failure_reason": "no_file_present",
        },
    ]
    _write_csv(
        tmp_path / "data" / "review_queue" / "manual_files_still_required_r4_8h.csv",
        manual_rows,
        list(manual_rows[0].keys()),
    )

    # Source A file present and valid.
    dropzone_file = tmp_path / "data" / "manual_import_dropzone" / "r4_8e" / "source_a" / "source_a.csv"
    dropzone_file.parent.mkdir(parents=True, exist_ok=True)
    dropzone_file.write_text("award_id,recipient_name\n1,Alpha\n2,Beta\n", encoding="utf-8")

    # Empty credentials queue from R4.8H is valid input.
    _write_csv(
        tmp_path / "data" / "review_queue" / "credentials_still_required_r4_8h.csv",
        [],
        [
            "priority",
            "source_family",
            "expected_input",
            "endpoint_classification",
            "source_url_or_portal",
            "producer_script",
            "required_credentials_or_auth_status",
            "required_env_vars",
            "missing_env_vars",
            "credentials_available",
            "reason_blocked",
            "credential_check_status",
            "review_status",
        ],
    )

    endpoint_rows = [
        {
            "priority": "2",
            "expected_input": "data/staging/processed/source_b.csv",
            "source_family": "source_b",
            "producer_script": "scripts/dummy_endpoint.py",
            "endpoint_classification": "endpoint_requires_auth",
            "recommended_endpoint_action": "configure_access_credentials_then_retry",
            "target_output_path": "data/staging/processed/source_b.csv",
            "required_env_vars": "",
            "missing_env_vars": "",
            "credentials_available": "False",
            "retry_attempted": "False",
            "retry_status": "credential_missing",
            "retry_command": "python scripts/dummy_endpoint.py",
            "command_exit_code": "",
            "command_excerpt_safe": "",
            "row_count": "0",
            "sha256": "",
            "manifest_written": "False",
            "validation_status": "",
            "failure_reason": "missing credentials",
            "review_status": "pending_credentials",
            "source_url_or_portal": "https://example.test/b",
            "required_credentials_or_auth_status": "auth_required",
        }
    ]
    _write_csv(
        tmp_path / "data" / "review_queue" / "endpoints_still_blocked_r4_8h.csv",
        endpoint_rows,
        list(endpoint_rows[0].keys()),
    )

    producer_rows = [
        {
            "priority": "3",
            "expected_input": "data/staging/processed/source_c.csv",
            "source_family": "source_c",
            "producer_script": "scripts/dummy_producer.py",
            "target_output_path": "data/staging/processed/source_c.csv",
            "patch_safe_now": "False",
            "manual_source_required": "False",
            "deterministic_patch_applied": "False",
            "required_env_vars": "",
            "missing_env_vars": "",
            "retry_attempted": "False",
            "retry_status": "patch_not_safe_now",
            "retry_command": "",
            "command_exit_code": "",
            "command_excerpt_safe": "",
            "row_count": "0",
            "sha256": "",
            "manifest_written": "False",
            "validation_status": "",
            "failure_reason": "patch pending review",
            "review_status": "pending_patch_review",
        }
    ]
    _write_csv(
        tmp_path / "data" / "review_queue" / "producers_still_blocked_r4_8h.csv",
        producer_rows,
        list(producer_rows[0].keys()),
    )

    _write_csv(
        tmp_path / "data" / "review_queue" / "backfill_retry_order_r4_8h.csv",
        [
            {
                "retry_rank": "1",
                "priority": "1",
                "expected_input": "data/staging/processed/source_a.csv",
                "source_family": "source_a",
                "next_action": "require_manual_file",
                "reason": "no_file_present",
            }
        ],
        ["retry_rank", "priority", "expected_input", "source_family", "next_action", "reason"],
    )

    _write_json(
        tmp_path / "data" / "exports" / "rebuild_status.json",
        {
            "r4_8h_rows_ingested_total": 10,
            "r4_8h_production_inputs_staged_total": 1,
            "r4_8h_validated_source_manifests_total": 1,
            "phase_7_8_blocked": True,
            "row_fabrication_policy": "FORBIDDEN_NO_SYNTHETIC_ROWS",
        },
    )

    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    (scripts_dir / "dummy_endpoint.py").write_text(
        "import os\n_ = os.getenv('DUMMY_ENDPOINT_TOKEN', '')\nprint('noop')\n",
        encoding="utf-8",
    )
    (scripts_dir / "dummy_producer.py").write_text(
        "import os\n_ = os.getenv('DUMMY_PRODUCER_TOKEN', '')\nprint('noop')\n",
        encoding="utf-8",
    )


def test_r48i_runs_and_writes_outputs(tmp_path: Path):
    _bootstrap_inputs(tmp_path)

    result = run_final_source_recovery_pass(tmp_path, command_timeout_seconds=1)

    assert result["r4_8i_gate_passed"] is True
    assert result["r4_8i_manual_requests_checked"] == 2
    assert result["r4_8i_manual_files_found"] == 1
    assert result["r4_8i_manual_files_validated"] == 1
    assert result["r4_8i_manual_files_still_required"] == 1
    assert result["r4_8i_endpoint_retries_attempted"] == 0
    assert result["r4_8i_endpoint_retries_successful"] == 0
    assert result["r4_8i_producer_retries_attempted"] == 0
    assert result["r4_8i_producer_retries_successful"] == 0
    assert result["r4_8i_new_rows_ingested"] == 2
    assert result["r4_8i_new_production_inputs_staged"] == 1
    assert result["r4_8i_new_validated_source_manifests"] == 1
    assert result["r4_8i_rows_ingested_total"] == 12
    assert result["r4_8i_production_inputs_staged_total"] == 2
    assert result["r4_8i_validated_source_manifests_total"] == 2
    assert result["r4_8i_external_blocker_count"] >= 1
    assert result["r4_8i_forbidden_artifact_usage"] is False
    assert result["phase_7_8_blocked"] is True

    assert (tmp_path / "data" / "exports" / "final_source_recovery_status_r4_8i.json").exists()
    assert (tmp_path / "data" / "exports" / "final_source_recovery_results_r4_8i.csv").exists()
    assert (tmp_path / "data" / "exports" / "external_acquisition_blocker_package_r4_8i.json").exists()
    assert (tmp_path / "data" / "exports" / "external_acquisition_blocker_package_r4_8i.md").exists()
    assert (tmp_path / "data" / "exports" / "validated_source_manifest_inventory_r4_8i.csv").exists()
    assert (tmp_path / "data" / "review_queue" / "manual_files_still_required_r4_8i.csv").exists()
    assert (tmp_path / "data" / "review_queue" / "endpoints_still_blocked_r4_8i.csv").exists()
    assert (tmp_path / "data" / "review_queue" / "producers_still_blocked_r4_8i.csv").exists()
    assert (tmp_path / "data" / "review_queue" / "backfill_retry_order_r4_8i.csv").exists()


def test_r48i_blocks_forbidden_artifact_path(tmp_path: Path):
    _bootstrap_inputs(tmp_path)

    manual_path = tmp_path / "data" / "review_queue" / "manual_files_still_required_r4_8h.csv"
    rows = list(csv.DictReader(manual_path.open(encoding="utf-8")))
    rows[0]["expected_input"] = "data/staging/processed/investigative_report.csv"
    _write_csv(manual_path, rows, list(rows[0].keys()))

    result = run_final_source_recovery_pass(tmp_path, command_timeout_seconds=1)

    assert result["r4_8i_gate_passed"] is False
    assert result["r4_8i_forbidden_artifact_usage"] is True
