"""Tests for R4.8E manual fallback and endpoint/producer resolution."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from scripts.run_manual_fallback_endpoint_resolution_r48e import (
    run_manual_fallback_endpoint_resolution,
)


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
    _write_json(
        tmp_path / "data" / "exports" / "targeted_backfill_retry_status_r4_8d.json",
        {
            "r4_8d_gate_passed": True,
            "r4_8d_rows_ingested": 3135,
            "r4_8d_production_inputs_staged": 7,
            "r4_8d_validated_source_manifests_written": 7,
            "phase_7_8_blocked": True,
            "row_fabrication_policy": "FORBIDDEN_NO_SYNTHETIC_ROWS",
        },
    )

    retry_results_rows = [
        {
            "priority": "1",
            "retry_rank": "1",
            "expected_input": "data/staging/processed/pr_contracts_master.csv",
            "source_family": "usaspending_federal_awards_backbone",
            "primary_blocker_class": "no_data",
            "retry_eligible": "True",
            "retry_attempted": "True",
            "retry_status": "failed_no_data",
            "target_output_path": "data/staging/processed/pr_contracts_master.csv",
            "row_count": "0",
            "validation_status": "",
            "manifest_written": "False",
            "failure_reason": "target output has zero rows",
            "producer_script": "scripts/deduplicate_master.py",
            "command": "python scripts/deduplicate_master.py",
            "patched_command": "",
            "command_exit_code": "0",
            "command_excerpt_safe": "No normalized files found",
            "schema_alignment_status": "",
            "schema_alignment_added_count": "0",
            "forbidden_artifact_usage": "False",
            "manual_fallback_required": "True",
            "disposition": "manual_fallback_required",
        },
        {
            "priority": "2",
            "retry_rank": "2",
            "expected_input": "data/staging/processed/pr_grants_master.csv",
            "source_family": "usaspending_federal_awards_backbone",
            "primary_blocker_class": "endpoint_unavailable",
            "retry_eligible": "False",
            "retry_attempted": "False",
            "retry_status": "not_retried_endpoint_unavailable",
            "target_output_path": "data/staging/processed/pr_grants_master.csv",
            "row_count": "0",
            "validation_status": "",
            "manifest_written": "False",
            "failure_reason": "endpoint unavailable source left queued",
            "producer_script": "scripts/download_grants.py",
            "command": "python scripts/download_grants.py --force",
            "patched_command": "",
            "command_exit_code": "",
            "command_excerpt_safe": "",
            "schema_alignment_status": "",
            "schema_alignment_added_count": "0",
            "forbidden_artifact_usage": "False",
            "manual_fallback_required": "True",
            "disposition": "manual_fallback_required",
        },
    ]
    _write_csv(
        tmp_path / "data" / "exports" / "targeted_backfill_retry_results_r4_8d.csv",
        retry_results_rows,
        list(retry_results_rows[0].keys()),
    )

    _write_csv(
        tmp_path / "data" / "exports" / "validated_source_manifest_inventory_r4_8d.csv",
        [
            {
                "source_system": "slfrf",
                "source_file": "data/staging/processed/pr_slfrf_master.csv",
                "target_output_path": "data/staging/processed/pr_slfrf_master.csv",
                "row_count": "200",
                "sha256": "abc",
                "generated_at": "2026-05-08T20:00:00Z",
                "producer_script": "scripts/download_slfrf.py",
                "validation_status": "validated",
                "known_gaps": "",
                "schema_version": "r4_8d_schema_v1",
                "manifest_type": "validated_source_manifest",
                "manifest_path": "data/manifests/r4_8d/08_pr_slfrf_master.manifest.json",
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
            "expected_input": "data/staging/processed/pr_contracts_master.csv",
            "source_family": "usaspending_federal_awards_backbone",
            "retry_status": "failed_no_data",
            "failure_reason": "target output has zero rows",
            "target_output_path": "data/staging/processed/pr_contracts_master.csv",
            "next_action": "manual_fallback_required",
        },
        {
            "priority": "2",
            "expected_input": "data/staging/processed/pr_grants_master.csv",
            "source_family": "usaspending_federal_awards_backbone",
            "retry_status": "not_retried_endpoint_unavailable",
            "failure_reason": "endpoint unavailable source left queued",
            "target_output_path": "data/staging/processed/pr_grants_master.csv",
            "next_action": "manual_fallback_required",
        },
    ]
    _write_csv(
        tmp_path / "data" / "review_queue" / "manual_fallback_remaining_r4_8d.csv",
        manual_rows,
        list(manual_rows[0].keys()),
    )

    endpoint_rows = [
        {
            "priority": "2",
            "expected_input": "data/staging/processed/pr_grants_master.csv",
            "source_family": "usaspending_federal_awards_backbone",
            "retry_status": "not_retried_endpoint_unavailable",
            "failure_reason": "endpoint unavailable source left queued",
            "next_action": "endpoint_review",
        }
    ]
    _write_csv(
        tmp_path / "data" / "review_queue" / "unresolved_endpoint_failures_r4_8d.csv",
        endpoint_rows,
        list(endpoint_rows[0].keys()),
    )

    producer_rows = [
        {
            "priority": "1",
            "expected_input": "data/staging/processed/pr_contracts_master.csv",
            "source_family": "usaspending_federal_awards_backbone",
            "producer_script": "scripts/deduplicate_master.py",
            "retry_status": "failed_no_data",
            "failure_reason": "target output has zero rows",
            "next_action": "producer_patch_or_manual_fallback",
        }
    ]
    _write_csv(
        tmp_path / "data" / "review_queue" / "unresolved_producer_failures_r4_8d.csv",
        producer_rows,
        list(producer_rows[0].keys()),
    )

    retry_order_rows = [
        {
            "retry_rank": "1",
            "priority": "1",
            "expected_input": "data/staging/processed/pr_contracts_master.csv",
            "source_family": "usaspending_federal_awards_backbone",
            "primary_blocker_class": "no_data",
            "retry_attempted": "True",
            "retry_status": "failed_no_data",
            "disposition": "manual_fallback_required",
            "next_action": "manual_fallback_required",
        },
        {
            "retry_rank": "2",
            "priority": "2",
            "expected_input": "data/staging/processed/pr_grants_master.csv",
            "source_family": "usaspending_federal_awards_backbone",
            "primary_blocker_class": "endpoint_unavailable",
            "retry_attempted": "False",
            "retry_status": "not_retried_endpoint_unavailable",
            "disposition": "manual_fallback_required",
            "next_action": "endpoint_review",
        },
    ]
    _write_csv(
        tmp_path / "data" / "review_queue" / "backfill_retry_order_r4_8d.csv",
        retry_order_rows,
        list(retry_order_rows[0].keys()),
    )

    runner_rows = [
        {
            "priority": "1",
            "classification": "automated_backfill_available",
            "expected_input": "data/staging/processed/pr_contracts_master.csv",
            "source_family": "usaspending_federal_awards_backbone",
            "likely_producer_script": "scripts/deduplicate_master.py",
            "target_output_path": "data/staging/processed/pr_contracts_master.csv",
            "expected_schema": "contract_id|vendor_name|source_system|source_record_id",
            "automated_command": "python scripts/deduplicate_master.py",
            "manual_steps": "",
            "requires_api_key": "False",
            "required_env_vars": "",
            "requires_manual_export": "False",
            "source_url_or_portal": "https://api.usaspending.gov",
            "validation_command": "python -c \"print(1)\"",
            "blocker_reason": "",
            "dry_run_command": "",
            "real_run_command_template": "python scripts/deduplicate_master.py",
            "forbidden_artifact_usage": "False",
        },
        {
            "priority": "2",
            "classification": "automated_backfill_available",
            "expected_input": "data/staging/processed/pr_grants_master.csv",
            "source_family": "usaspending_federal_awards_backbone",
            "likely_producer_script": "scripts/download_grants.py",
            "target_output_path": "data/staging/processed/pr_grants_master.csv",
            "expected_schema": "award_id|recipient_name|source_system|source_record_id",
            "automated_command": "python scripts/download_grants.py --force",
            "manual_steps": "",
            "requires_api_key": "False",
            "required_env_vars": "",
            "requires_manual_export": "False",
            "source_url_or_portal": "https://api.usaspending.gov",
            "validation_command": "python -c \"print(1)\"",
            "blocker_reason": "",
            "dry_run_command": "",
            "real_run_command_template": "python scripts/download_grants.py --force",
            "forbidden_artifact_usage": "False",
        },
    ]
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
            "r4_8d_rows_ingested": 3135,
            "r4_8d_production_inputs_staged": 7,
            "r4_8d_validated_source_manifests_written": 7,
        },
    )


def test_r48e_builds_outputs_and_passes_gate(tmp_path: Path):
    _bootstrap_inputs(tmp_path)

    result = run_manual_fallback_endpoint_resolution(
        tmp_path,
        enable_endpoint_probes=False,
    )

    assert result["r4_8e_gate_passed"] is True
    assert result["r4_8e_manual_fallback_sources"] == 2
    assert result["r4_8e_endpoint_failures_reviewed"] == 1
    assert result["r4_8e_producer_failures_reviewed"] == 1
    assert result["r4_8e_manual_files_required"] == 2
    assert result["r4_8e_endpoint_followup_required"] == 1
    assert result["r4_8e_rows_ingested"] == 3135
    assert result["r4_8e_production_inputs_staged"] == 7
    assert result["r4_8e_validated_source_manifests_written"] == 7
    assert result["r4_8e_forbidden_artifact_usage"] is False
    assert result["phase_7_8_blocked"] is True

    assert (tmp_path / "data" / "exports" / "manual_fallback_package_r4_8e.json").exists()
    assert (tmp_path / "data" / "exports" / "manual_fallback_inventory_r4_8e.csv").exists()
    assert (tmp_path / "data" / "exports" / "endpoint_resolution_report_r4_8e.csv").exists()
    assert (tmp_path / "data" / "exports" / "producer_failure_resolution_report_r4_8e.csv").exists()
    assert (tmp_path / "data" / "review_queue" / "manual_files_required_r4_8e.csv").exists()
    assert (tmp_path / "data" / "review_queue" / "endpoint_followup_required_r4_8e.csv").exists()
    assert (tmp_path / "data" / "review_queue" / "producer_patch_remaining_r4_8e.csv").exists()
    assert (tmp_path / "data" / "review_queue" / "backfill_retry_order_r4_8e.csv").exists()


def test_r48e_blocks_forbidden_artifact_paths(tmp_path: Path):
    _bootstrap_inputs(tmp_path)

    manual_path = tmp_path / "data" / "review_queue" / "manual_fallback_remaining_r4_8d.csv"
    rows = list(csv.DictReader(manual_path.open(encoding="utf-8")))
    rows[0]["expected_input"] = "data/staging/processed/investigative_report.csv"
    _write_csv(manual_path, rows, list(rows[0].keys()))

    result = run_manual_fallback_endpoint_resolution(
        tmp_path,
        enable_endpoint_probes=False,
    )

    assert result["r4_8e_gate_passed"] is False
    assert result["r4_8e_forbidden_artifact_usage"] is True
