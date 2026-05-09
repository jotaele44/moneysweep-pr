"""Tests for R4.8H manual fulfillment and credentialed endpoint retry orchestration."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from contract_sweeper.pipeline.final_backfill_retry import run_final_backfill_retry


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
        tmp_path / "data" / "exports" / "acquisition_package_r4_8g.json",
        {
            "r4_8g_gate_passed": True,
            "r4_8g_manual_file_requests": 2,
            "r4_8g_credential_requests": 1,
            "r4_8g_endpoint_resolution_requests": 1,
            "r4_8g_producer_patch_requests": 1,
            "phase_7_8_blocked": True,
            "row_fabrication_policy": "FORBIDDEN_NO_SYNTHETIC_ROWS",
        },
    )
    (tmp_path / "data" / "exports" / "acquisition_package_r4_8g.md").write_text(
        "# package\n",
        encoding="utf-8",
    )

    manual_rows = [
        {
            "priority": "1",
            "source_family": "source_a",
            "expected_input": "data/staging/processed/source_a.csv",
            "source_url_or_portal": "https://example.test/a",
            "exact_manual_export_steps": "step",
            "required_file_type": "csv",
            "accepted_filename_patterns": "source_a.csv|source_a*.csv",
            "required_columns": "award_id|recipient_name",
            "target_dropzone_path": "data/manual_import_dropzone/r4_8e/source_a/source_a.csv",
            "target_output_path": "data/staging/processed/source_a.csv",
            "validation_command": "python -c \"print('ok')\"",
            "reason_needed": "no_file_present",
            "request_status": "pending_manual_delivery",
        },
        {
            "priority": "2",
            "source_family": "source_b",
            "expected_input": "data/staging/processed/source_b.csv",
            "source_url_or_portal": "https://example.test/b",
            "exact_manual_export_steps": "step",
            "required_file_type": "csv",
            "accepted_filename_patterns": "source_b.csv|source_b*.csv",
            "required_columns": "award_id|recipient_name",
            "target_dropzone_path": "data/manual_import_dropzone/r4_8e/source_b/source_b.csv",
            "target_output_path": "data/staging/processed/source_b.csv",
            "validation_command": "python -c \"print('ok')\"",
            "reason_needed": "no_file_present",
            "request_status": "pending_manual_delivery",
        },
    ]

    _write_csv(
        tmp_path / "data" / "review_queue" / "manual_file_requests_r4_8g.csv",
        manual_rows,
        list(manual_rows[0].keys()),
    )
    _write_csv(
        tmp_path / "data" / "exports" / "manual_file_acquisition_matrix_r4_8g.csv",
        [{k: v for k, v in row.items() if k != "request_status"} for row in manual_rows],
        [k for k in manual_rows[0].keys() if k != "request_status"],
    )

    # Dropzone file present for source_a only.
    dropzone_file = tmp_path / "data" / "manual_import_dropzone" / "r4_8e" / "source_a" / "source_a.csv"
    dropzone_file.parent.mkdir(parents=True, exist_ok=True)
    dropzone_file.write_text("award_id,recipient_name\n1,Alpha\n2,Beta\n", encoding="utf-8")

    credential_rows = [
        {
            "priority": "2",
            "source_family": "source_b",
            "expected_input": "data/staging/processed/source_b.csv",
            "endpoint_classification": "endpoint_requires_auth",
            "source_url_or_portal": "https://example.test/b",
            "producer_script": "scripts/dummy_endpoint.py",
            "required_credentials_or_auth_status": "auth_or_permission_required",
            "recommended_endpoint_action": "configure_access_credentials_then_retry",
            "safe_retry_command_if_available": "python scripts/dummy_endpoint.py",
            "reason_blocked": "credential unavailable",
            "credential_request_reason": "needs token",
        }
    ]
    _write_csv(
        tmp_path / "data" / "review_queue" / "credential_requests_r4_8g.csv",
        credential_rows,
        list(credential_rows[0].keys()),
    )
    _write_csv(
        tmp_path / "data" / "exports" / "credential_unblock_plan_r4_8g.csv",
        credential_rows,
        list(credential_rows[0].keys()),
    )

    endpoint_rows = [
        {
            "priority": "2",
            "source_family": "source_b",
            "expected_input": "data/staging/processed/source_b.csv",
            "endpoint_classification": "endpoint_requires_auth",
            "source_url_or_portal": "https://example.test/b",
            "producer_script": "scripts/dummy_endpoint.py",
            "required_credentials_or_auth_status": "auth_or_permission_required",
            "recommended_endpoint_action": "configure_access_credentials_then_retry",
            "safe_retry_command_if_available": "python scripts/dummy_endpoint.py",
            "reason_blocked": "credential unavailable",
        }
    ]
    _write_csv(
        tmp_path / "data" / "review_queue" / "endpoint_resolution_requests_r4_8g.csv",
        endpoint_rows,
        list(endpoint_rows[0].keys()),
    )

    producer_rows = [
        {
            "priority": "3",
            "source_family": "source_c",
            "expected_input": "data/staging/processed/source_c.csv",
            "producer_script": "scripts/dummy_producer.py",
            "failure_reason": "command failed",
            "recommended_patch": "safe deterministic patch",
            "patch_safe_now": "True",
            "manual_source_required": "False",
        }
    ]
    _write_csv(
        tmp_path / "data" / "review_queue" / "producer_patch_requests_r4_8g.csv",
        producer_rows,
        list(producer_rows[0].keys()),
    )

    _write_csv(
        tmp_path / "data" / "review_queue" / "backfill_retry_order_r4_8g.csv",
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

    _write_csv(
        tmp_path / "data" / "exports" / "validated_source_manifest_inventory_r4_8f.csv",
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

    _write_json(
        tmp_path / "data" / "exports" / "rebuild_status.json",
        {
            "r4_8g_rows_ingested_total": 10,
            "r4_8g_production_inputs_staged_total": 1,
            "r4_8g_validated_source_manifests_total": 1,
            "phase_7_8_blocked": True,
            "row_fabrication_policy": "FORBIDDEN_NO_SYNTHETIC_ROWS",
        },
    )

    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    (scripts_dir / "dummy_endpoint.py").write_text(
        "import os\nTOKEN=os.getenv('DUMMY_ENDPOINT_TOKEN','')\nprint('token-set' if TOKEN else 'token-missing')\n",
        encoding="utf-8",
    )
    (scripts_dir / "dummy_producer.py").write_text(
        "import os\nTOKEN=os.getenv('DUMMY_PRODUCER_TOKEN','')\nprint('token-set' if TOKEN else 'token-missing')\n",
        encoding="utf-8",
    )


def test_r48h_runs_and_writes_outputs(tmp_path: Path):
    _bootstrap_inputs(tmp_path)

    result = run_final_backfill_retry(tmp_path, command_timeout_seconds=1)

    assert result["r4_8h_gate_passed"] is True
    assert result["r4_8h_manual_requests_checked"] == 2
    assert result["r4_8h_manual_files_found"] == 1
    assert result["r4_8h_manual_files_validated"] == 1
    assert result["r4_8h_manual_files_still_required"] == 1
    assert result["r4_8h_credential_requests_checked"] == 1
    assert result["r4_8h_credentials_available"] == 0
    assert result["r4_8h_credentials_still_required"] == 1
    assert result["r4_8h_endpoint_retries_attempted"] == 0
    assert result["r4_8h_endpoint_retries_successful"] == 0
    assert result["r4_8h_producer_patches_applied"] == 0
    assert result["r4_8h_producer_retries_attempted"] == 0
    assert result["r4_8h_producer_retries_successful"] == 0
    assert result["r4_8h_new_rows_ingested"] == 2
    assert result["r4_8h_new_production_inputs_staged"] == 1
    assert result["r4_8h_new_validated_source_manifests"] == 1
    assert result["r4_8h_rows_ingested_total"] == 12
    assert result["r4_8h_production_inputs_staged_total"] == 2
    assert result["r4_8h_validated_source_manifests_total"] == 2
    assert result["r4_8h_forbidden_artifact_usage"] is False
    assert result["phase_7_8_blocked"] is True

    assert (tmp_path / "data" / "exports" / "manual_fulfillment_endpoint_retry_status_r4_8h.json").exists()
    assert (tmp_path / "data" / "exports" / "manual_fulfillment_results_r4_8h.csv").exists()
    assert (tmp_path / "data" / "exports" / "credentialed_endpoint_retry_results_r4_8h.csv").exists()
    assert (tmp_path / "data" / "exports" / "final_backfill_retry_results_r4_8h.csv").exists()
    assert (tmp_path / "data" / "exports" / "validated_source_manifest_inventory_r4_8h.csv").exists()
    assert (tmp_path / "data" / "review_queue" / "manual_files_still_required_r4_8h.csv").exists()
    assert (tmp_path / "data" / "review_queue" / "credentials_still_required_r4_8h.csv").exists()
    assert (tmp_path / "data" / "review_queue" / "endpoints_still_blocked_r4_8h.csv").exists()
    assert (tmp_path / "data" / "review_queue" / "producers_still_blocked_r4_8h.csv").exists()
    assert (tmp_path / "data" / "review_queue" / "backfill_retry_order_r4_8h.csv").exists()


def test_r48h_blocks_forbidden_artifact_path(tmp_path: Path):
    _bootstrap_inputs(tmp_path)

    manual_path = tmp_path / "data" / "review_queue" / "manual_file_requests_r4_8g.csv"
    rows = list(csv.DictReader(manual_path.open(encoding="utf-8")))
    rows[0]["expected_input"] = "data/staging/processed/investigative_report.csv"
    _write_csv(manual_path, rows, list(rows[0].keys()))

    result = run_final_backfill_retry(tmp_path, command_timeout_seconds=1)

    assert result["r4_8h_gate_passed"] is False
    assert result["r4_8h_forbidden_artifact_usage"] is True
