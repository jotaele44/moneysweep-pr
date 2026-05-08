"""Tests for R4.8 controlled backfill execution and manual import validation."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from contract_sweeper.pipeline.controlled_backfill import run_controlled_backfill


MANIFEST_FIELDS = [
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


def _bootstrap_inputs(tmp_path: Path, manifest_rows: list[dict], import_slot_rows: list[dict] | None = None) -> None:
    _write_json(tmp_path / "data" / "exports" / "backfill_runner_plan_r4_7.json", {})
    _write_csv(tmp_path / "data" / "exports" / "backfill_runner_manifest_r4_7.csv", manifest_rows, MANIFEST_FIELDS)

    _write_csv(
        tmp_path / "data" / "exports" / "import_slots_r4_7.csv",
        import_slot_rows or [],
        [
            "slot_id",
            "source_family",
            "expected_input",
            "dropzone_path",
            "accepted_file_patterns",
            "required_columns",
            "target_output_path",
            "validation_command",
            "manifest_output_path",
        ],
    )

    _write_csv(
        tmp_path / "data" / "exports" / "backfill_execution_plan_r4_6.csv",
        [
            {
                "priority": idx + 1,
                "expected_input": row["expected_input"],
                "acceptance_gate": "file_exists AND rows>0",
            }
            for idx, row in enumerate(manifest_rows)
        ],
        ["priority", "expected_input", "acceptance_gate"],
    )

    _write_json(
        tmp_path / "data" / "exports" / "backfill_execution_plan_r4_6_status.json",
        {"row_fabrication_policy": "FORBIDDEN_NO_SYNTHETIC_ROWS"},
    )
    _write_json(
        tmp_path / "data" / "exports" / "rebuild_status.json",
        {"phase_7_8_blocked": True, "row_fabrication_policy": "FORBIDDEN_NO_SYNTHETIC_ROWS"},
    )


def test_r48_dry_run_defaults_and_classifies_sources(tmp_path: Path):
    manifest_rows = [
        {
            "priority": 1,
            "classification": "automated_backfill_available",
            "expected_input": "data/staging/processed/pr_grants_master.csv",
            "source_family": "usaspending",
            "likely_producer_script": "scripts/download_grants.py",
            "target_output_path": "data/staging/processed/pr_grants_master.csv",
            "expected_schema": "award_id|recipient_name",
            "automated_command": "python scripts/download_grants.py --force",
            "manual_steps": "",
            "requires_api_key": False,
            "required_env_vars": "",
            "requires_manual_export": False,
            "source_url_or_portal": "https://api.usaspending.gov",
            "validation_command": "python -c 'print(1)'",
            "blocker_reason": "",
            "dry_run_command": "DRY_RUN: python scripts/download_grants.py --force",
            "real_run_command_template": "python scripts/download_grants.py --force",
            "forbidden_artifact_usage": False,
        },
        {
            "priority": 2,
            "classification": "automated_backfill_available",
            "expected_input": "data/staging/processed/pr_hud_master.csv",
            "source_family": "hud_cdbg",
            "likely_producer_script": "scripts/download_hud.py",
            "target_output_path": "data/staging/processed/pr_hud_master.csv",
            "expected_schema": "award_id|recipient_name",
            "automated_command": "python scripts/download_hud.py --force",
            "manual_steps": "",
            "requires_api_key": True,
            "required_env_vars": "HUD_API_KEY",
            "requires_manual_export": False,
            "source_url_or_portal": "https://example.test/hud",
            "validation_command": "python -c 'print(1)'",
            "blocker_reason": "",
            "dry_run_command": "DRY_RUN: python scripts/download_hud.py --force",
            "real_run_command_template": "python scripts/download_hud.py --force",
            "forbidden_artifact_usage": False,
        },
        {
            "priority": 3,
            "classification": "manual_import_required",
            "expected_input": "data/staging/processed/pr_custom_master.csv",
            "source_family": "custom",
            "likely_producer_script": "",
            "target_output_path": "data/staging/processed/pr_custom_master.csv",
            "expected_schema": "award_id|recipient_name",
            "automated_command": "",
            "manual_steps": "manual import",
            "requires_api_key": False,
            "required_env_vars": "",
            "requires_manual_export": True,
            "source_url_or_portal": "https://example.test/custom",
            "validation_command": "python -c 'print(1)'",
            "blocker_reason": "",
            "dry_run_command": "",
            "real_run_command_template": "",
            "forbidden_artifact_usage": False,
        },
    ]
    _bootstrap_inputs(tmp_path, manifest_rows)

    result = run_controlled_backfill(tmp_path, dry_run=True, execute_downloads=False)

    assert result["r4_8_gate_passed"] is True
    assert result["r4_8_total_sources"] == 3
    assert result["r4_8_dry_run_ready_count"] == 1
    assert result["r4_8_executable_with_credentials_count"] == 0
    assert result["r4_8_missing_credentials_count"] == 1
    assert result["r4_8_manual_import_required_count"] == 1
    assert result["r4_8_missing_schema_count"] == 0
    assert result["r4_8_blocked_count"] == 0
    assert result["r4_8_downloads_executed"] is False
    assert result["r4_8_rows_ingested"] == 0
    assert result["r4_8_production_inputs_staged"] == 0
    assert result["r4_8_source_manifests_written"] == 3
    assert result["row_fabrication_policy"] == "FORBIDDEN_NO_SYNTHETIC_ROWS"
    assert result["phase_7_8_blocked"] is True
    assert result["secrets_required_count"] == 1


def test_r48_execute_downloads_requires_credentials(tmp_path: Path):
    manifest_rows = [
        {
            "priority": 1,
            "classification": "automated_backfill_available",
            "expected_input": "data/staging/processed/pr_epa_master.csv",
            "source_family": "epa",
            "likely_producer_script": "scripts/download_epa.py",
            "target_output_path": "data/staging/processed/pr_epa_master.csv",
            "expected_schema": "award_id|recipient_name",
            "automated_command": "python scripts/download_epa.py --force",
            "manual_steps": "",
            "requires_api_key": True,
            "required_env_vars": "EPA_API_KEY",
            "requires_manual_export": False,
            "source_url_or_portal": "https://example.test/epa",
            "validation_command": "python -c 'print(1)'",
            "blocker_reason": "",
            "dry_run_command": "DRY_RUN: python scripts/download_epa.py --force",
            "real_run_command_template": "python scripts/download_epa.py --force",
            "forbidden_artifact_usage": False,
        }
    ]
    _bootstrap_inputs(tmp_path, manifest_rows)

    result = run_controlled_backfill(tmp_path, dry_run=False, execute_downloads=True)

    assert result["r4_8_gate_passed"] is True
    assert result["r4_8_missing_credentials_count"] == 1
    assert result["r4_8_executable_with_credentials_count"] == 0
    assert result["r4_8_downloads_executed"] is False
    assert result["r4_8_rows_ingested"] == 0
    assert result["r4_8_production_inputs_staged"] == 0
    assert result["secrets_required_count"] == 1
    assert result["phase_7_8_blocked"] is True


def test_r48_rejects_forbidden_artifacts(tmp_path: Path):
    manifest_rows = [
        {
            "priority": 1,
            "classification": "automated_backfill_available",
            "expected_input": "data/staging/processed/pr_grants_summary.csv",
            "source_family": "usaspending",
            "likely_producer_script": "scripts/download_grants.py",
            "target_output_path": "data/staging/processed/pr_grants_summary.csv",
            "expected_schema": "award_id|recipient_name",
            "automated_command": "python scripts/download_grants.py --force",
            "manual_steps": "",
            "requires_api_key": False,
            "required_env_vars": "",
            "requires_manual_export": False,
            "source_url_or_portal": "https://api.usaspending.gov",
            "validation_command": "python -c 'print(1)'",
            "blocker_reason": "",
            "dry_run_command": "DRY_RUN: python scripts/download_grants.py --force",
            "real_run_command_template": "python scripts/download_grants.py --force",
            "forbidden_artifact_usage": False,
        }
    ]
    _bootstrap_inputs(tmp_path, manifest_rows)

    result = run_controlled_backfill(tmp_path, dry_run=True, execute_downloads=False)

    assert result["forbidden_artifact_usage"] is True
    assert result["r4_8_blocked_count"] == 1
    assert result["r4_8_gate_passed"] is False
