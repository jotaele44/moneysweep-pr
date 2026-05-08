"""Tests for R4.8A controlled backfill readiness audit."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from contract_sweeper.pipeline.backfill_readiness_audit import run_backfill_readiness_audit


CONTROLLED_FIELDS = [
    "priority",
    "expected_input",
    "source_family",
    "target_output_path",
    "classification",
    "planned_action",
    "expected_schema",
]

RUNNER_FIELDS = [
    "priority",
    "classification",
    "expected_input",
    "source_family",
    "likely_producer_script",
    "target_output_path",
    "expected_schema",
    "automated_command",
    "manual_steps",
    "requires_api_key",
    "required_env_vars",
    "requires_manual_export",
    "source_url_or_portal",
    "validation_command",
    "blocker_reason",
    "dry_run_command",
    "real_run_command_template",
    "forbidden_artifact_usage",
]


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _bootstrap(tmp_path: Path, *, controlled_rows: list[dict], runner_rows: list[dict], source_rows: list[dict]) -> None:
    _write_json(
        tmp_path / "data" / "exports" / "controlled_backfill_plan_r4_8.json",
        {"row_fabrication_policy": "FORBIDDEN_NO_SYNTHETIC_ROWS"},
    )
    _write_csv(
        tmp_path / "data" / "exports" / "controlled_backfill_manifest_r4_8.csv",
        controlled_rows,
        CONTROLLED_FIELDS,
    )
    _write_csv(
        tmp_path / "data" / "exports" / "source_manifest_inventory_r4_8.csv",
        source_rows,
        [
            "source_system",
            "source_file",
            "source_record_count",
            "source_sha256",
            "generated_at",
            "producer_script",
            "target_output_path",
            "schema_version",
            "validation_status",
            "known_gaps",
        ],
    )
    _write_csv(
        tmp_path / "data" / "exports" / "backfill_runner_manifest_r4_7.csv",
        runner_rows,
        RUNNER_FIELDS,
    )
    _write_csv(
        tmp_path / "data" / "exports" / "backfill_execution_plan_r4_6.csv",
        [
            {
                "priority": idx + 1,
                "expected_input": row["expected_input"],
            }
            for idx, row in enumerate(controlled_rows)
        ],
        ["priority", "expected_input"],
    )
    _write_json(
        tmp_path / "data" / "exports" / "rebuild_status.json",
        {"phase_7_8_blocked": True, "row_fabrication_policy": "FORBIDDEN_NO_SYNTHETIC_ROWS"},
    )


def test_r48a_classifies_and_queues_blockers(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("R48A_TEST_REQUIRED_KEY", raising=False)

    script_ok = tmp_path / "scripts" / "download_ok.py"
    script_ok.parent.mkdir(parents=True, exist_ok=True)
    script_ok.write_text("print('ok')\n", encoding="utf-8")

    controlled_rows = [
        {
            "priority": 1,
            "expected_input": "data/staging/processed/pr_ok_master.csv",
            "source_family": "ok_source",
            "target_output_path": "data/staging/processed/pr_ok_master.csv",
            "classification": "dry_run_ready",
            "planned_action": "emit_dry_run_plan",
            "expected_schema": "award_id|recipient_name",
        },
        {
            "priority": 2,
            "expected_input": "data/staging/processed/pr_cred_master.csv",
            "source_family": "cred_source",
            "target_output_path": "data/staging/processed/pr_cred_master.csv",
            "classification": "dry_run_ready",
            "planned_action": "emit_dry_run_plan",
            "expected_schema": "award_id|recipient_name",
        },
        {
            "priority": 3,
            "expected_input": "data/staging/processed/pr_manual_master.csv",
            "source_family": "manual_source",
            "target_output_path": "data/staging/processed/pr_manual_master.csv",
            "classification": "manual_import_required",
            "planned_action": "route_to_manual_import_slot",
            "expected_schema": "award_id|recipient_name",
        },
    ]

    runner_rows = [
        {
            "priority": 1,
            "classification": "automated_backfill_available",
            "expected_input": "data/staging/processed/pr_ok_master.csv",
            "source_family": "ok_source",
            "likely_producer_script": "scripts/download_ok.py",
            "target_output_path": "data/staging/processed/pr_ok_master.csv",
            "expected_schema": "award_id|recipient_name",
            "automated_command": "python scripts/download_ok.py",
            "manual_steps": "",
            "requires_api_key": False,
            "required_env_vars": "",
            "requires_manual_export": False,
            "source_url_or_portal": "https://example.test/ok",
            "validation_command": "python -c 'print(1)'",
            "blocker_reason": "",
            "dry_run_command": "DRY_RUN: python scripts/download_ok.py",
            "real_run_command_template": "python scripts/download_ok.py",
            "forbidden_artifact_usage": False,
        },
        {
            "priority": 2,
            "classification": "automated_backfill_available",
            "expected_input": "data/staging/processed/pr_cred_master.csv",
            "source_family": "cred_source",
            "likely_producer_script": "scripts/download_ok.py",
            "target_output_path": "data/staging/processed/pr_cred_master.csv",
            "expected_schema": "award_id|recipient_name",
            "automated_command": "python scripts/download_ok.py",
            "manual_steps": "",
            "requires_api_key": True,
            "required_env_vars": "R48A_TEST_REQUIRED_KEY",
            "requires_manual_export": False,
            "source_url_or_portal": "https://example.test/cred",
            "validation_command": "python -c 'print(1)'",
            "blocker_reason": "",
            "dry_run_command": "DRY_RUN: python scripts/download_ok.py",
            "real_run_command_template": "python scripts/download_ok.py",
            "forbidden_artifact_usage": False,
        },
        {
            "priority": 3,
            "classification": "manual_import_required",
            "expected_input": "data/staging/processed/pr_manual_master.csv",
            "source_family": "manual_source",
            "likely_producer_script": "",
            "target_output_path": "data/staging/processed/pr_manual_master.csv",
            "expected_schema": "award_id|recipient_name",
            "automated_command": "",
            "manual_steps": "manual import",
            "requires_api_key": False,
            "required_env_vars": "",
            "requires_manual_export": True,
            "source_url_or_portal": "https://example.test/manual",
            "validation_command": "python -c 'print(1)'",
            "blocker_reason": "",
            "dry_run_command": "",
            "real_run_command_template": "",
            "forbidden_artifact_usage": False,
        },
    ]

    source_rows = [
        {
            "source_system": "ok_source",
            "source_file": "data/staging/processed/pr_ok_master.csv",
            "source_record_count": 0,
            "source_sha256": "",
            "generated_at": "2026-05-08T00:00:00Z",
            "producer_script": "scripts/download_ok.py",
            "target_output_path": "data/staging/processed/pr_ok_master.csv",
            "schema_version": "r4_8_schema_v1",
            "validation_status": "dry_run_ready",
            "known_gaps": "",
        },
        {
            "source_system": "cred_source",
            "source_file": "data/staging/processed/pr_cred_master.csv",
            "source_record_count": 0,
            "source_sha256": "",
            "generated_at": "2026-05-08T00:00:00Z",
            "producer_script": "scripts/download_ok.py",
            "target_output_path": "data/staging/processed/pr_cred_master.csv",
            "schema_version": "r4_8_schema_v1",
            "validation_status": "dry_run_ready",
            "known_gaps": "",
        },
        {
            "source_system": "manual_source",
            "source_file": "data/staging/processed/pr_manual_master.csv",
            "source_record_count": 0,
            "source_sha256": "",
            "generated_at": "2026-05-08T00:00:00Z",
            "producer_script": "",
            "target_output_path": "data/staging/processed/pr_manual_master.csv",
            "schema_version": "r4_8_schema_v1",
            "validation_status": "manual_import_required",
            "known_gaps": "",
        },
    ]

    _bootstrap(tmp_path, controlled_rows=controlled_rows, runner_rows=runner_rows, source_rows=source_rows)

    result = run_backfill_readiness_audit(tmp_path)

    assert result["r4_8a_gate_passed"] is True
    assert result["r4_8a_total_sources"] == 3
    assert result["r4_8a_ready_for_execute_downloads_count"] == 1
    assert result["r4_8a_requires_credentials_count"] == 1
    assert result["r4_8a_requires_manual_file_count"] == 1
    assert result["r4_8a_requires_schema_mapping_count"] == 0
    assert result["r4_8a_requires_producer_script_count"] == 0
    assert result["r4_8a_blocked_count"] == 0
    assert result["r4_8a_downloads_executed"] is False
    assert result["r4_8a_rows_ingested"] == 0
    assert result["r4_8a_production_inputs_staged"] == 0
    assert result["r4_8a_validated_source_manifests_written"] == 0
    assert result["phase_7_8_blocked"] is True


def test_r48a_detects_missing_producer_script(tmp_path: Path):
    controlled_rows = [
        {
            "priority": 1,
            "expected_input": "data/staging/processed/pr_missing_script.csv",
            "source_family": "missing_script",
            "target_output_path": "data/staging/processed/pr_missing_script.csv",
            "classification": "dry_run_ready",
            "planned_action": "emit_dry_run_plan",
            "expected_schema": "award_id|recipient_name",
        }
    ]

    runner_rows = [
        {
            "priority": 1,
            "classification": "automated_backfill_available",
            "expected_input": "data/staging/processed/pr_missing_script.csv",
            "source_family": "missing_script",
            "likely_producer_script": "scripts/download_missing.py",
            "target_output_path": "data/staging/processed/pr_missing_script.csv",
            "expected_schema": "award_id|recipient_name",
            "automated_command": "python scripts/download_missing.py",
            "manual_steps": "",
            "requires_api_key": False,
            "required_env_vars": "",
            "requires_manual_export": False,
            "source_url_or_portal": "https://example.test/missing",
            "validation_command": "python -c 'print(1)'",
            "blocker_reason": "",
            "dry_run_command": "DRY_RUN: python scripts/download_missing.py",
            "real_run_command_template": "python scripts/download_missing.py",
            "forbidden_artifact_usage": False,
        }
    ]

    source_rows = [
        {
            "source_system": "missing_script",
            "source_file": "data/staging/processed/pr_missing_script.csv",
            "source_record_count": 0,
            "source_sha256": "",
            "generated_at": "2026-05-08T00:00:00Z",
            "producer_script": "scripts/download_missing.py",
            "target_output_path": "data/staging/processed/pr_missing_script.csv",
            "schema_version": "r4_8_schema_v1",
            "validation_status": "dry_run_ready",
            "known_gaps": "",
        }
    ]

    _bootstrap(tmp_path, controlled_rows=controlled_rows, runner_rows=runner_rows, source_rows=source_rows)

    result = run_backfill_readiness_audit(tmp_path)

    assert result["r4_8a_gate_passed"] is True
    assert result["r4_8a_requires_producer_script_count"] == 1


def test_r48a_rejects_forbidden_artifact_input(tmp_path: Path):
    controlled_rows = [
        {
            "priority": 1,
            "expected_input": "data/staging/processed/pr_graph_summary.csv",
            "source_family": "forbidden",
            "target_output_path": "data/staging/processed/pr_graph_summary.csv",
            "classification": "dry_run_ready",
            "planned_action": "emit_dry_run_plan",
            "expected_schema": "award_id|recipient_name",
        }
    ]

    runner_rows = [
        {
            "priority": 1,
            "classification": "automated_backfill_available",
            "expected_input": "data/staging/processed/pr_graph_summary.csv",
            "source_family": "forbidden",
            "likely_producer_script": "scripts/download_ok.py",
            "target_output_path": "data/staging/processed/pr_graph_summary.csv",
            "expected_schema": "award_id|recipient_name",
            "automated_command": "python scripts/download_ok.py",
            "manual_steps": "",
            "requires_api_key": False,
            "required_env_vars": "",
            "requires_manual_export": False,
            "source_url_or_portal": "https://example.test/forbidden",
            "validation_command": "python -c 'print(1)'",
            "blocker_reason": "",
            "dry_run_command": "DRY_RUN: python scripts/download_ok.py",
            "real_run_command_template": "python scripts/download_ok.py",
            "forbidden_artifact_usage": False,
        }
    ]

    source_rows = [
        {
            "source_system": "forbidden",
            "source_file": "data/staging/processed/pr_graph_summary.csv",
            "source_record_count": 0,
            "source_sha256": "",
            "generated_at": "2026-05-08T00:00:00Z",
            "producer_script": "scripts/download_ok.py",
            "target_output_path": "data/staging/processed/pr_graph_summary.csv",
            "schema_version": "r4_8_schema_v1",
            "validation_status": "dry_run_ready",
            "known_gaps": "",
        }
    ]

    _bootstrap(tmp_path, controlled_rows=controlled_rows, runner_rows=runner_rows, source_rows=source_rows)

    result = run_backfill_readiness_audit(tmp_path)

    assert result["r4_8a_gate_passed"] is False
    assert result["forbidden_artifact_usage"] is True
    assert result["r4_8a_blocked_count"] == 1
