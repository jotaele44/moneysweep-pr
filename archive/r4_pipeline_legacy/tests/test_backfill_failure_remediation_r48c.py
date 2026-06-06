"""Tests for R4.8C backfill failure remediation."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from contract_sweeper.pipeline.backfill_failure_remediation import run_backfill_failure_remediation


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _bootstrap_inputs(tmp_path: Path) -> None:
    readiness_rows = [
        {
            "priority": "1",
            "expected_input": "data/staging/processed/source_a.csv",
            "source_family": "family_a",
            "readiness": "ready_for_execute_downloads",
            "next_action": "ready",
            "reason": "",
            "producer_script": "scripts/download_a.py",
            "producer_script_exists": "True",
            "required_env_vars": "",
            "credentials_present": "True",
            "missing_env_vars": "",
            "target_output_path": "data/staging/processed/source_a.csv",
            "expected_schema_known": "True",
            "validation_command": "python -c \"print(1)\"",
            "has_validation_command": "True",
            "manifest_path": "data/staging/processed/source_a.csv.manifest.json",
            "planning_manifest_present": "True",
            "validated_manifest_present": "False",
            "manual_path_required": "False",
            "dropzone_path": "",
            "accepted_file_patterns": "",
            "forbidden_artifact_usage": "False",
            "row_fabrication_policy": "FORBIDDEN_NO_SYNTHETIC_ROWS",
        },
        {
            "priority": "2",
            "expected_input": "data/staging/processed/source_b.csv",
            "source_family": "family_b",
            "readiness": "ready_for_execute_downloads",
            "next_action": "ready",
            "reason": "",
            "producer_script": "scripts/download_b.py",
            "producer_script_exists": "True",
            "required_env_vars": "",
            "credentials_present": "True",
            "missing_env_vars": "",
            "target_output_path": "data/staging/processed/source_b.csv",
            "expected_schema_known": "True",
            "validation_command": "python -c \"print(1)\"",
            "has_validation_command": "True",
            "manifest_path": "data/staging/processed/source_b.csv.manifest.json",
            "planning_manifest_present": "True",
            "validated_manifest_present": "False",
            "manual_path_required": "False",
            "dropzone_path": "",
            "accepted_file_patterns": "",
            "forbidden_artifact_usage": "False",
            "row_fabrication_policy": "FORBIDDEN_NO_SYNTHETIC_ROWS",
        },
        {
            "priority": "3",
            "expected_input": "data/staging/processed/source_c.csv",
            "source_family": "family_c",
            "readiness": "ready_for_execute_downloads",
            "next_action": "ready",
            "reason": "",
            "producer_script": "scripts/download_c.py",
            "producer_script_exists": "True",
            "required_env_vars": "",
            "credentials_present": "True",
            "missing_env_vars": "",
            "target_output_path": "data/staging/processed/source_c.csv",
            "expected_schema_known": "True",
            "validation_command": "python -c \"print(1)\"",
            "has_validation_command": "True",
            "manifest_path": "data/staging/processed/source_c.csv.manifest.json",
            "planning_manifest_present": "True",
            "validated_manifest_present": "False",
            "manual_path_required": "False",
            "dropzone_path": "",
            "accepted_file_patterns": "",
            "forbidden_artifact_usage": "False",
            "row_fabrication_policy": "FORBIDDEN_NO_SYNTHETIC_ROWS",
        },
    ]

    results_rows = [
        {
            "priority": "1",
            "expected_input": "data/staging/processed/source_a.csv",
            "source_family": "family_a",
            "readiness": "ready_for_execute_downloads",
            "terminal_status": "execution_timeout",
            "attempted": "True",
            "skipped_reason": "",
            "target_output_path": "data/staging/processed/source_a.csv",
            "producer_script": "scripts/download_a.py",
            "command": "python scripts/download_a.py",
            "command_executed": "True",
            "command_exit_code": "124",
            "required_env_vars": "",
            "missing_env_vars": "",
            "output_exists": "False",
            "row_count": "0",
            "schema_valid": "False",
            "validation_command": "python -c \"print(1)\"",
            "validation_executed": "False",
            "validation_exit_code": "",
            "validated_manifest_path": "",
            "validated_manifest_written": "False",
            "blocker_reason": "command timed out after 20s",
            "next_action": "retry",
            "forbidden_artifact_usage": "False",
            "target_hash_before": "",
            "target_hash_after": "",
            "target_changed": "False",
            "target_sha256": "",
        },
        {
            "priority": "2",
            "expected_input": "data/staging/processed/source_b.csv",
            "source_family": "family_b",
            "readiness": "ready_for_execute_downloads",
            "terminal_status": "schema_failure",
            "attempted": "True",
            "skipped_reason": "",
            "target_output_path": "data/staging/processed/source_b.csv",
            "producer_script": "scripts/download_b.py",
            "command": "python scripts/download_b.py",
            "command_executed": "True",
            "command_exit_code": "0",
            "required_env_vars": "",
            "missing_env_vars": "",
            "output_exists": "True",
            "row_count": "1",
            "schema_valid": "False",
            "validation_command": "python -c \"print(1)\"",
            "validation_executed": "False",
            "validation_exit_code": "",
            "validated_manifest_path": "",
            "validated_manifest_written": "False",
            "blocker_reason": "missing required columns",
            "next_action": "repair",
            "forbidden_artifact_usage": "False",
            "target_hash_before": "",
            "target_hash_after": "abc",
            "target_changed": "True",
            "target_sha256": "abc",
        },
        {
            "priority": "3",
            "expected_input": "data/staging/processed/source_c.csv",
            "source_family": "family_c",
            "readiness": "ready_for_execute_downloads",
            "terminal_status": "no_data",
            "attempted": "True",
            "skipped_reason": "",
            "target_output_path": "data/staging/processed/source_c.csv",
            "producer_script": "scripts/download_c.py",
            "command": "python scripts/download_c.py",
            "command_executed": "True",
            "command_exit_code": "0",
            "required_env_vars": "",
            "missing_env_vars": "",
            "output_exists": "False",
            "row_count": "0",
            "schema_valid": "False",
            "validation_command": "python -c \"print(1)\"",
            "validation_executed": "False",
            "validation_exit_code": "",
            "validated_manifest_path": "",
            "validated_manifest_written": "False",
            "blocker_reason": "target output not produced",
            "next_action": "retry",
            "forbidden_artifact_usage": "False",
            "target_hash_before": "",
            "target_hash_after": "",
            "target_changed": "False",
            "target_sha256": "",
        },
    ]

    failures_rows = [
        {
            "priority": "1",
            "expected_input": "data/staging/processed/source_a.csv",
            "source_family": "family_a",
            "terminal_status": "execution_timeout",
            "reason": "command timed out after 20s",
            "attempted": "True",
            "command_executed": "True",
            "command_exit_code": "124",
            "next_action": "retry",
        },
        {
            "priority": "2",
            "expected_input": "data/staging/processed/source_b.csv",
            "source_family": "family_b",
            "terminal_status": "schema_failure",
            "reason": "missing required columns",
            "attempted": "True",
            "command_executed": "True",
            "command_exit_code": "0",
            "next_action": "repair",
        },
        {
            "priority": "3",
            "expected_input": "data/staging/processed/source_c.csv",
            "source_family": "family_c",
            "terminal_status": "no_data",
            "reason": "target output not produced",
            "attempted": "True",
            "command_executed": "True",
            "command_exit_code": "0",
            "next_action": "retry",
        },
    ]

    runner_rows = [
        {
            "priority": "1",
            "classification": "automated_backfill_available",
            "expected_input": "data/staging/processed/source_a.csv",
            "source_family": "family_a",
            "likely_producer_script": "scripts/download_a.py",
            "target_output_path": "data/staging/processed/source_a.csv",
            "expected_schema": "award_id|recipient_name",
            "automated_command": "python scripts/download_a.py",
            "manual_steps": "",
            "requires_api_key": "False",
            "required_env_vars": "",
            "requires_manual_export": "False",
            "source_url_or_portal": "https://example.test/a",
            "validation_command": "python -c \"print(1)\"",
            "blocker_reason": "",
            "dry_run_command": "",
            "real_run_command_template": "python scripts/download_a.py",
            "forbidden_artifact_usage": "False",
        },
        {
            "priority": "2",
            "classification": "automated_backfill_available",
            "expected_input": "data/staging/processed/source_b.csv",
            "source_family": "family_b",
            "likely_producer_script": "scripts/download_b.py",
            "target_output_path": "data/staging/processed/source_b.csv",
            "expected_schema": "award_id|recipient_name|source_system",
            "automated_command": "python scripts/download_b.py",
            "manual_steps": "",
            "requires_api_key": "False",
            "required_env_vars": "",
            "requires_manual_export": "False",
            "source_url_or_portal": "https://example.test/b",
            "validation_command": "python -c \"print(1)\"",
            "blocker_reason": "",
            "dry_run_command": "",
            "real_run_command_template": "python scripts/download_b.py",
            "forbidden_artifact_usage": "False",
        },
        {
            "priority": "3",
            "classification": "automated_backfill_available",
            "expected_input": "data/staging/processed/source_c.csv",
            "source_family": "family_c",
            "likely_producer_script": "scripts/download_c.py",
            "target_output_path": "data/staging/processed/source_c.csv",
            "expected_schema": "award_id|recipient_name",
            "automated_command": "python scripts/download_c.py",
            "manual_steps": "",
            "requires_api_key": "False",
            "required_env_vars": "",
            "requires_manual_export": "False",
            "source_url_or_portal": "https://example.test/c",
            "validation_command": "python -c \"print(1)\"",
            "blocker_reason": "",
            "dry_run_command": "",
            "real_run_command_template": "python scripts/download_c.py",
            "forbidden_artifact_usage": "False",
        },
    ]

    schema_failures_rows = [
        {
            "priority": "2",
            "expected_input": "data/staging/processed/source_b.csv",
            "source_family": "family_b",
            "target_output_path": "data/staging/processed/source_b.csv",
            "expected_schema": "award_id|recipient_name|source_system",
            "missing_columns": "source_system",
            "validation_exit_code": "",
            "reason": "missing required columns",
            "next_action": "repair",
        }
    ]

    manual_rows = [
        {
            "priority": "1",
            "expected_input": "data/staging/processed/source_a.csv",
            "source_family": "family_a",
            "terminal_status": "execution_timeout",
            "reason": "command timed out after 20s",
            "next_action": "retry",
        },
        {
            "priority": "2",
            "expected_input": "data/staging/processed/source_b.csv",
            "source_family": "family_b",
            "terminal_status": "schema_failure",
            "reason": "missing required columns",
            "next_action": "repair",
        },
        {
            "priority": "3",
            "expected_input": "data/staging/processed/source_c.csv",
            "source_family": "family_c",
            "terminal_status": "no_data",
            "reason": "target output not produced",
            "next_action": "retry",
        },
    ]

    _write_json(
        tmp_path / "data" / "exports" / "controlled_backfill_execution_status_r4_8b.json",
        {
            "r4_8b_total_sources": 3,
            "r4_8b_failed_sources": 3,
            "row_fabrication_policy": "FORBIDDEN_NO_SYNTHETIC_ROWS",
            "phase_7_8_blocked": True,
        },
    )

    _write_csv(
        tmp_path / "data" / "exports" / "controlled_backfill_execution_results_r4_8b.csv",
        results_rows,
        list(results_rows[0].keys()),
    )
    _write_csv(
        tmp_path / "data" / "review_queue" / "controlled_backfill_execution_failures_r4_8b.csv",
        failures_rows,
        list(failures_rows[0].keys()),
    )
    _write_csv(
        tmp_path / "data" / "review_queue" / "schema_failures_r4_8b.csv",
        schema_failures_rows,
        list(schema_failures_rows[0].keys()),
    )
    _write_csv(
        tmp_path / "data" / "review_queue" / "manual_fallback_required_r4_8b.csv",
        manual_rows,
        list(manual_rows[0].keys()),
    )
    _write_csv(
        tmp_path / "data" / "review_queue" / "no_data_sources_r4_8b.csv",
        [
            {
                "priority": "3",
                "expected_input": "data/staging/processed/source_c.csv",
                "source_family": "family_c",
                "target_output_path": "data/staging/processed/source_c.csv",
                "reason": "target output not produced",
                "next_action": "retry",
            }
        ],
        ["priority", "expected_input", "source_family", "target_output_path", "reason", "next_action"],
    )
    _write_csv(
        tmp_path / "data" / "review_queue" / "credential_failures_r4_8b.csv",
        [],
        [
            "priority",
            "expected_input",
            "source_family",
            "producer_script",
            "required_env_vars",
            "missing_env_vars",
            "reason",
            "next_action",
        ],
    )

    _write_csv(
        tmp_path / "data" / "exports" / "backfill_readiness_matrix_r4_8a.csv",
        readiness_rows,
        list(readiness_rows[0].keys()),
    )
    _write_csv(
        tmp_path / "data" / "exports" / "backfill_execution_plan_r4_6.csv",
        [
            {
                "priority": "1",
                "expected_input": "data/staging/processed/source_a.csv",
                "dataset_label": "a",
                "input_group": "core",
                "recommended_action": "run a",
                "source_of_truth": "src",
                "producer_script": "scripts/download_a.py",
                "producer_command": "python scripts/download_a.py",
                "precheck_required": "none",
                "acceptance_gate": "rows>0",
                "lineage_manifest_required": "True",
                "row_fabrication_policy": "FORBIDDEN_NO_SYNTHETIC_ROWS",
                "on_failure": "queue",
                "output_path": "data/staging/processed/source_a.csv",
            },
            {
                "priority": "2",
                "expected_input": "data/staging/processed/source_b.csv",
                "dataset_label": "b",
                "input_group": "core",
                "recommended_action": "run b",
                "source_of_truth": "src",
                "producer_script": "scripts/download_b.py",
                "producer_command": "python scripts/download_b.py",
                "precheck_required": "none",
                "acceptance_gate": "rows>0",
                "lineage_manifest_required": "True",
                "row_fabrication_policy": "FORBIDDEN_NO_SYNTHETIC_ROWS",
                "on_failure": "queue",
                "output_path": "data/staging/processed/source_b.csv",
            },
            {
                "priority": "3",
                "expected_input": "data/staging/processed/source_c.csv",
                "dataset_label": "c",
                "input_group": "core",
                "recommended_action": "run c",
                "source_of_truth": "src",
                "producer_script": "scripts/download_c.py",
                "producer_command": "python scripts/download_c.py",
                "precheck_required": "none",
                "acceptance_gate": "rows>0",
                "lineage_manifest_required": "True",
                "row_fabrication_policy": "FORBIDDEN_NO_SYNTHETIC_ROWS",
                "on_failure": "queue",
                "output_path": "data/staging/processed/source_c.csv",
            },
        ],
        [
            "priority",
            "expected_input",
            "dataset_label",
            "input_group",
            "recommended_action",
            "source_of_truth",
            "producer_script",
            "producer_command",
            "precheck_required",
            "acceptance_gate",
            "lineage_manifest_required",
            "row_fabrication_policy",
            "on_failure",
            "output_path",
        ],
    )
    _write_csv(
        tmp_path / "data" / "exports" / "backfill_runner_manifest_r4_7.csv",
        runner_rows,
        list(runner_rows[0].keys()),
    )
    _write_json(
        tmp_path / "data" / "exports" / "rebuild_status.json",
        {
            "phase_7_8_blocked": True,
            "row_fabrication_policy": "FORBIDDEN_NO_SYNTHETIC_ROWS",
        },
    )

    # Source B observed columns intentionally missing source_system.
    data_path = tmp_path / "data" / "staging" / "processed"
    data_path.mkdir(parents=True, exist_ok=True)
    (data_path / "source_b.csv").write_text("award_id,recipient_name\n1,Acme\n", encoding="utf-8")


def test_r48c_builds_remediation_outputs_and_passes_gate(tmp_path: Path):
    _bootstrap_inputs(tmp_path)

    result = run_backfill_failure_remediation(tmp_path)

    assert result["r4_8c_gate_passed"] is True
    assert result["r4_8c_total_failed_sources"] == 3
    assert result["r4_8c_schema_remediation_count"] == 1
    assert result["r4_8c_manual_fallback_count"] == 3
    assert result["r4_8c_producer_fix_count"] == 2
    assert result["r4_8c_endpoint_review_count"] == 1
    assert result["r4_8c_retry_order_count"] == 3
    assert result["r4_8c_downloads_executed"] is False
    assert result["r4_8c_rows_ingested"] == 0
    assert result["r4_8c_production_inputs_staged"] == 0
    assert result["r4_8c_validated_source_manifests_written"] == 0
    assert result["phase_7_8_blocked"] is True

    counts = result["r4_8c_primary_blocker_counts"]
    assert counts["endpoint_unavailable"] == 1
    assert counts["schema_mismatch"] == 1
    assert counts["no_data"] == 1


def test_r48c_schema_queue_has_remediation_details(tmp_path: Path):
    _bootstrap_inputs(tmp_path)

    run_backfill_failure_remediation(tmp_path)

    schema_rows = list(
        csv.DictReader(
            (tmp_path / "data" / "review_queue" / "schema_remediation_queue_r4_8c.csv").open(
                encoding="utf-8"
            )
        )
    )
    assert len(schema_rows) == 1
    row = schema_rows[0]
    assert row["expected_input"] == "data/staging/processed/source_b.csv"
    assert "source_system" in row["missing_columns"]
    assert "recommended_mapping" in row
    assert row["recommended_mapping"]


def test_r48c_rejects_forbidden_artifact_inputs(tmp_path: Path):
    _bootstrap_inputs(tmp_path)

    # Mutate one failure/input to forbidden artifact path.
    failures_path = tmp_path / "data" / "review_queue" / "controlled_backfill_execution_failures_r4_8b.csv"
    rows = list(csv.DictReader(failures_path.open(encoding="utf-8")))
    rows[0]["expected_input"] = "data/staging/processed/source_report.csv"
    _write_csv(failures_path, rows, list(rows[0].keys()))

    result = run_backfill_failure_remediation(tmp_path)

    assert result["r4_8c_gate_passed"] is False
    assert result["forbidden_artifact_usage"] is True
