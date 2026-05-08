"""Tests for R4.8 controlled backfill execution and manual import validation."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from contract_sweeper.pipeline.backfill_execution import run_backfill_execution


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _manifest_row(*, output_path: str, dry_run_command: str, real_run_command: str) -> dict:
    return {
        "priority": 1,
        "classification": "automated_backfill_available",
        "expected_input": output_path,
        "source_family": "test_source",
        "likely_producer_script": "scripts/make_output.py",
        "target_output_path": output_path,
        "expected_schema": "award_id|recipient_name",
        "automated_command": real_run_command,
        "manual_steps": "",
        "requires_api_key": False,
        "required_env_vars": "",
        "requires_manual_export": False,
        "source_url_or_portal": "https://example.test",
        "validation_command": "python -c 'print(1)'",
        "blocker_reason": "",
        "dry_run_command": dry_run_command,
        "real_run_command_template": real_run_command,
        "forbidden_artifact_usage": False,
    }


def _setup_common_files(tmp_path: Path) -> None:
    _write_json(
        tmp_path / "data" / "exports" / "backfill_runner_plan_r4_7.json",
        {"row_fabrication_policy": "FORBIDDEN_NO_SYNTHETIC_ROWS"},
    )
    _write_json(
        tmp_path / "data" / "exports" / "rebuild_status.json",
        {"phase_7_8_blocked": True, "row_fabrication_policy": "FORBIDDEN_NO_SYNTHETIC_ROWS"},
    )


def test_r48_default_dry_run_does_not_execute_downloads(tmp_path: Path):
    _setup_common_files(tmp_path)

    output_rel = "data/staging/processed/pr_grants_master.csv"
    output_path = tmp_path / output_rel
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("award_id,recipient_name\nA1,Alpha\n", encoding="utf-8")

    _write_csv(
        tmp_path / "data" / "exports" / "backfill_runner_manifest_r4_7.csv",
        [
            _manifest_row(
                output_path=output_rel,
                dry_run_command="DRY_RUN: python scripts/make_output.py",
                real_run_command="python scripts/make_output.py",
            )
        ],
        [
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
        ],
    )
    _write_csv(
        tmp_path / "data" / "exports" / "import_slots_r4_7.csv",
        [],
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

    result = run_backfill_execution(tmp_path, dry_run=True, execute_downloads=False)

    assert result["r4_8_gate_passed"] is True
    assert result["r4_8_execute_downloads_default"] is False
    assert result["r4_8_downloads_executed"] is False
    assert result["r4_8_executed_download_commands"] == 0
    assert result["phase_7_8_blocked"] is True
    assert result["row_fabrication_policy"] == "FORBIDDEN_NO_SYNTHETIC_ROWS"


def test_r48_execute_downloads_is_explicit_opt_in(tmp_path: Path):
    _setup_common_files(tmp_path)

    output_rel = "data/staging/processed/pr_subawards_master.csv"
    script_path = tmp_path / "scripts" / "make_output.py"
    script_path.parent.mkdir(parents=True, exist_ok=True)
    script_path.write_text(
        "from pathlib import Path\n"
        "p=Path('data/staging/processed/pr_subawards_master.csv')\n"
        "p.parent.mkdir(parents=True, exist_ok=True)\n"
        "p.write_text('award_id,recipient_name\\nS1,Sigma\\n', encoding='utf-8')\n",
        encoding="utf-8",
    )

    _write_csv(
        tmp_path / "data" / "exports" / "backfill_runner_manifest_r4_7.csv",
        [
            _manifest_row(
                output_path=output_rel,
                dry_run_command="DRY_RUN: python scripts/make_output.py",
                real_run_command="python scripts/make_output.py",
            )
        ],
        [
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
        ],
    )
    _write_csv(
        tmp_path / "data" / "exports" / "import_slots_r4_7.csv",
        [],
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

    result = run_backfill_execution(tmp_path, dry_run=False, execute_downloads=True)

    assert result["r4_8_gate_passed"] is True
    assert result["r4_8_downloads_executed"] is True
    assert result["r4_8_executed_download_commands"] == 1
    assert result["r4_8_successful_download_commands"] == 1
    assert result["r4_8_rows_ingested_during_run"] > 0


def test_r48_manual_slot_missing_blocks_gate(tmp_path: Path):
    _setup_common_files(tmp_path)

    output_rel = "data/staging/processed/pr_epa_master.csv"
    output_path = tmp_path / output_rel
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("award_id,recipient_name\nE1,Echo\n", encoding="utf-8")

    _write_csv(
        tmp_path / "data" / "exports" / "backfill_runner_manifest_r4_7.csv",
        [
            _manifest_row(
                output_path=output_rel,
                dry_run_command="DRY_RUN: python scripts/make_output.py",
                real_run_command="python scripts/make_output.py",
            )
        ],
        [
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
        ],
    )
    _write_csv(
        tmp_path / "data" / "exports" / "import_slots_r4_7.csv",
        [
            {
                "slot_id": "slot_01_pr_hud_master",
                "source_family": "hud_cdbg",
                "expected_input": "data/staging/processed/pr_hud_master.csv",
                "dropzone_path": "data/manual_import_dropzone/hud_cdbg/pr_hud_master.csv",
                "accepted_file_patterns": "*.csv",
                "required_columns": "award_id|recipient_name",
                "target_output_path": "data/staging/processed/pr_hud_master.csv",
                "validation_command": "python -c 'print(1)'",
                "manifest_output_path": "data/staging/processed/pr_hud_master.csv.manifest.json",
            }
        ],
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

    result = run_backfill_execution(tmp_path, dry_run=True, execute_downloads=False)

    assert result["r4_8_gate_passed"] is False
    assert result["r4_8_manual_slots_total"] == 1
    assert result["r4_8_manual_slots_missing"] == 1
    assert result["phase_7_8_blocked"] is True
