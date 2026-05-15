"""Tests for R4.8B controlled real backfill execution."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from contract_sweeper.pipeline.controlled_backfill_execution import run_controlled_backfill_execution

READINESS_FIELDS = [
    "priority",
    "expected_input",
    "source_family",
    "readiness",
    "next_action",
    "reason",
    "producer_script",
    "producer_script_exists",
    "required_env_vars",
    "credentials_present",
    "missing_env_vars",
    "target_output_path",
    "expected_schema_known",
    "validation_command",
    "has_validation_command",
    "manifest_path",
    "planning_manifest_present",
    "validated_manifest_present",
    "manual_path_required",
    "dropzone_path",
    "accepted_file_patterns",
    "forbidden_artifact_usage",
    "row_fabrication_policy",
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

CONTROLLED_FIELDS = [
    "priority",
    "expected_input",
    "source_family",
    "target_output_path",
    "classification",
    "planned_action",
    "dry_run_mode",
    "execute_downloads_requested",
    "command_selected",
    "command_executed",
    "command_exit_code",
    "command_output_excerpt",
    "required_env_vars",
    "missing_env_vars",
    "expected_schema",
    "expected_acceptance_gate",
    "blocker_reason",
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


def _bootstrap(tmp_path: Path, readiness_rows: list[dict], runner_rows: list[dict]) -> None:
    _write_csv(
        tmp_path / "data" / "exports" / "backfill_readiness_matrix_r4_8a.csv",
        readiness_rows,
        READINESS_FIELDS,
    )

    _write_json(
        tmp_path / "data" / "exports" / "backfill_readiness_status_r4_8a.json",
        {
            "r4_8a_gate_passed": True,
            "r4_8a_total_sources": len(readiness_rows),
            "row_fabrication_policy": "FORBIDDEN_NO_SYNTHETIC_ROWS",
            "phase_7_8_blocked": True,
        },
    )

    _write_json(
        tmp_path / "data" / "exports" / "controlled_backfill_plan_r4_8.json",
        {
            "r4_8_gate_passed": True,
            "row_fabrication_policy": "FORBIDDEN_NO_SYNTHETIC_ROWS",
        },
    )

    _write_csv(
        tmp_path / "data" / "exports" / "controlled_backfill_manifest_r4_8.csv",
        [
            {
                "priority": row["priority"],
                "expected_input": row["expected_input"],
                "source_family": row["source_family"],
                "target_output_path": row["target_output_path"],
                "classification": "dry_run_ready",
                "planned_action": "emit_dry_run_plan",
                "dry_run_mode": True,
                "execute_downloads_requested": False,
                "command_selected": "",
                "command_executed": False,
                "command_exit_code": "",
                "command_output_excerpt": "",
                "required_env_vars": row.get("required_env_vars", ""),
                "missing_env_vars": row.get("missing_env_vars", ""),
                "expected_schema": "",
                "expected_acceptance_gate": "",
                "blocker_reason": "",
                "forbidden_artifact_usage": False,
            }
            for row in readiness_rows
        ],
        CONTROLLED_FIELDS,
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
                "priority": row["priority"],
                "expected_input": row["expected_input"],
                "acceptance_gate": "rows>0",
            }
            for row in readiness_rows
        ],
        ["priority", "expected_input", "acceptance_gate"],
    )

    _write_json(
        tmp_path / "data" / "exports" / "rebuild_status.json",
        {
            "phase_7_8_blocked": True,
            "row_fabrication_policy": "FORBIDDEN_NO_SYNTHETIC_ROWS",
        },
    )


def _make_script(path: Path, body: str) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return str(path.relative_to(path.parents[1]))


def test_r48b_executes_with_explicit_terminal_statuses(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("R48B_REQUIRED_KEY", raising=False)

    success_script = _make_script(
        tmp_path / "scripts" / "download_success.py",
        """
from pathlib import Path
import pandas as pd
p = Path('data/staging/processed/success.csv')
p.parent.mkdir(parents=True, exist_ok=True)
pd.DataFrame([{'award_id':'1','recipient_name':'A'}]).to_csv(p, index=False)
print('ok')
""".strip()
        + "\n",
    )

    nodata_script = _make_script(
        tmp_path / "scripts" / "download_nodata.py",
        """
from pathlib import Path
import pandas as pd
p = Path('data/staging/processed/nodata.csv')
p.parent.mkdir(parents=True, exist_ok=True)
pd.DataFrame(columns=['award_id','recipient_name']).to_csv(p, index=False)
print('no data')
""".strip()
        + "\n",
    )

    schema_script = _make_script(
        tmp_path / "scripts" / "download_bad_schema.py",
        """
from pathlib import Path
import pandas as pd
p = Path('data/staging/processed/schema_bad.csv')
p.parent.mkdir(parents=True, exist_ok=True)
pd.DataFrame([{'wrong_col':'x'}]).to_csv(p, index=False)
print('schema bad')
""".strip()
        + "\n",
    )

    fail_script = _make_script(
        tmp_path / "scripts" / "download_fail.py",
        """
raise SystemExit(2)
""".strip()
        + "\n",
    )

    credential_script = _make_script(
        tmp_path / "scripts" / "download_credential.py",
        """
print('should not execute without key')
""".strip()
        + "\n",
    )

    readiness_rows = [
        {
            "priority": 1,
            "expected_input": "data/staging/processed/success.csv",
            "source_family": "src_success",
            "readiness": "ready_for_execute_downloads",
            "next_action": "run",
            "reason": "",
            "producer_script": success_script,
            "producer_script_exists": True,
            "required_env_vars": "",
            "credentials_present": True,
            "missing_env_vars": "",
            "target_output_path": "data/staging/processed/success.csv",
            "expected_schema_known": True,
            "validation_command": "python -c \"print('valid')\"",
            "has_validation_command": True,
            "manifest_path": "data/staging/processed/success.csv.manifest.json",
            "planning_manifest_present": True,
            "validated_manifest_present": False,
            "manual_path_required": False,
            "dropzone_path": "",
            "accepted_file_patterns": "",
            "forbidden_artifact_usage": False,
            "row_fabrication_policy": "FORBIDDEN_NO_SYNTHETIC_ROWS",
        },
        {
            "priority": 2,
            "expected_input": "data/staging/processed/nodata.csv",
            "source_family": "src_nodata",
            "readiness": "ready_for_execute_downloads",
            "next_action": "run",
            "reason": "",
            "producer_script": nodata_script,
            "producer_script_exists": True,
            "required_env_vars": "",
            "credentials_present": True,
            "missing_env_vars": "",
            "target_output_path": "data/staging/processed/nodata.csv",
            "expected_schema_known": True,
            "validation_command": "python -c \"print('valid')\"",
            "has_validation_command": True,
            "manifest_path": "data/staging/processed/nodata.csv.manifest.json",
            "planning_manifest_present": True,
            "validated_manifest_present": False,
            "manual_path_required": False,
            "dropzone_path": "",
            "accepted_file_patterns": "",
            "forbidden_artifact_usage": False,
            "row_fabrication_policy": "FORBIDDEN_NO_SYNTHETIC_ROWS",
        },
        {
            "priority": 3,
            "expected_input": "data/staging/processed/schema_bad.csv",
            "source_family": "src_schema",
            "readiness": "ready_for_execute_downloads",
            "next_action": "run",
            "reason": "",
            "producer_script": schema_script,
            "producer_script_exists": True,
            "required_env_vars": "",
            "credentials_present": True,
            "missing_env_vars": "",
            "target_output_path": "data/staging/processed/schema_bad.csv",
            "expected_schema_known": True,
            "validation_command": "python -c \"print('valid')\"",
            "has_validation_command": True,
            "manifest_path": "data/staging/processed/schema_bad.csv.manifest.json",
            "planning_manifest_present": True,
            "validated_manifest_present": False,
            "manual_path_required": False,
            "dropzone_path": "",
            "accepted_file_patterns": "",
            "forbidden_artifact_usage": False,
            "row_fabrication_policy": "FORBIDDEN_NO_SYNTHETIC_ROWS",
        },
        {
            "priority": 4,
            "expected_input": "data/staging/processed/fail.csv",
            "source_family": "src_fail",
            "readiness": "ready_for_execute_downloads",
            "next_action": "run",
            "reason": "",
            "producer_script": fail_script,
            "producer_script_exists": True,
            "required_env_vars": "",
            "credentials_present": True,
            "missing_env_vars": "",
            "target_output_path": "data/staging/processed/fail.csv",
            "expected_schema_known": True,
            "validation_command": "python -c \"print('valid')\"",
            "has_validation_command": True,
            "manifest_path": "data/staging/processed/fail.csv.manifest.json",
            "planning_manifest_present": True,
            "validated_manifest_present": False,
            "manual_path_required": False,
            "dropzone_path": "",
            "accepted_file_patterns": "",
            "forbidden_artifact_usage": False,
            "row_fabrication_policy": "FORBIDDEN_NO_SYNTHETIC_ROWS",
        },
        {
            "priority": 5,
            "expected_input": "data/staging/processed/cred.csv",
            "source_family": "src_cred",
            "readiness": "ready_for_execute_downloads",
            "next_action": "run",
            "reason": "",
            "producer_script": credential_script,
            "producer_script_exists": True,
            "required_env_vars": "R48B_REQUIRED_KEY",
            "credentials_present": False,
            "missing_env_vars": "R48B_REQUIRED_KEY",
            "target_output_path": "data/staging/processed/cred.csv",
            "expected_schema_known": True,
            "validation_command": "python -c \"print('valid')\"",
            "has_validation_command": True,
            "manifest_path": "data/staging/processed/cred.csv.manifest.json",
            "planning_manifest_present": True,
            "validated_manifest_present": False,
            "manual_path_required": False,
            "dropzone_path": "",
            "accepted_file_patterns": "",
            "forbidden_artifact_usage": False,
            "row_fabrication_policy": "FORBIDDEN_NO_SYNTHETIC_ROWS",
        },
    ]

    runner_rows = [
        {
            "priority": 1,
            "classification": "automated_backfill_available",
            "expected_input": "data/staging/processed/success.csv",
            "source_family": "src_success",
            "likely_producer_script": success_script,
            "target_output_path": "data/staging/processed/success.csv",
            "expected_schema": "award_id|recipient_name",
            "automated_command": f"python {success_script}",
            "manual_steps": "",
            "requires_api_key": False,
            "required_env_vars": "",
            "requires_manual_export": False,
            "source_url_or_portal": "https://example.test/success",
            "validation_command": "python -c \"print('validate ok')\"",
            "blocker_reason": "",
            "dry_run_command": f"DRY_RUN: python {success_script}",
            "real_run_command_template": f"python {success_script}",
            "forbidden_artifact_usage": False,
        },
        {
            "priority": 2,
            "classification": "automated_backfill_available",
            "expected_input": "data/staging/processed/nodata.csv",
            "source_family": "src_nodata",
            "likely_producer_script": nodata_script,
            "target_output_path": "data/staging/processed/nodata.csv",
            "expected_schema": "award_id|recipient_name",
            "automated_command": f"python {nodata_script}",
            "manual_steps": "",
            "requires_api_key": False,
            "required_env_vars": "",
            "requires_manual_export": False,
            "source_url_or_portal": "https://example.test/nodata",
            "validation_command": "python -c \"print('validate ok')\"",
            "blocker_reason": "",
            "dry_run_command": f"DRY_RUN: python {nodata_script}",
            "real_run_command_template": f"python {nodata_script}",
            "forbidden_artifact_usage": False,
        },
        {
            "priority": 3,
            "classification": "automated_backfill_available",
            "expected_input": "data/staging/processed/schema_bad.csv",
            "source_family": "src_schema",
            "likely_producer_script": schema_script,
            "target_output_path": "data/staging/processed/schema_bad.csv",
            "expected_schema": "award_id|recipient_name",
            "automated_command": f"python {schema_script}",
            "manual_steps": "",
            "requires_api_key": False,
            "required_env_vars": "",
            "requires_manual_export": False,
            "source_url_or_portal": "https://example.test/schema",
            "validation_command": "python -c \"print('validate ok')\"",
            "blocker_reason": "",
            "dry_run_command": f"DRY_RUN: python {schema_script}",
            "real_run_command_template": f"python {schema_script}",
            "forbidden_artifact_usage": False,
        },
        {
            "priority": 4,
            "classification": "automated_backfill_available",
            "expected_input": "data/staging/processed/fail.csv",
            "source_family": "src_fail",
            "likely_producer_script": fail_script,
            "target_output_path": "data/staging/processed/fail.csv",
            "expected_schema": "award_id|recipient_name",
            "automated_command": f"python {fail_script}",
            "manual_steps": "",
            "requires_api_key": False,
            "required_env_vars": "",
            "requires_manual_export": False,
            "source_url_or_portal": "https://example.test/fail",
            "validation_command": "python -c \"print('validate ok')\"",
            "blocker_reason": "",
            "dry_run_command": f"DRY_RUN: python {fail_script}",
            "real_run_command_template": f"python {fail_script}",
            "forbidden_artifact_usage": False,
        },
        {
            "priority": 5,
            "classification": "automated_backfill_available",
            "expected_input": "data/staging/processed/cred.csv",
            "source_family": "src_cred",
            "likely_producer_script": credential_script,
            "target_output_path": "data/staging/processed/cred.csv",
            "expected_schema": "award_id|recipient_name",
            "automated_command": f"python {credential_script}",
            "manual_steps": "",
            "requires_api_key": True,
            "required_env_vars": "R48B_REQUIRED_KEY",
            "requires_manual_export": False,
            "source_url_or_portal": "https://example.test/cred",
            "validation_command": "python -c \"print('validate ok')\"",
            "blocker_reason": "",
            "dry_run_command": f"DRY_RUN: python {credential_script}",
            "real_run_command_template": f"python {credential_script}",
            "forbidden_artifact_usage": False,
        },
    ]

    _bootstrap(tmp_path, readiness_rows, runner_rows)

    status = run_controlled_backfill_execution(
        tmp_path,
        execute_downloads=True,
        command_timeout_s=30,
        validation_timeout_s=30,
    )

    assert status["r4_8b_gate_passed"] is True
    assert status["r4_8b_total_sources"] == 5
    assert status["r4_8b_attempted_sources"] == 4
    assert status["r4_8b_successful_sources"] == 1
    assert status["r4_8b_failed_sources"] == 4
    assert status["r4_8b_no_data_sources"] == 1
    assert status["r4_8b_credential_failures"] == 1
    assert status["r4_8b_schema_failures"] == 1
    assert status["r4_8b_manual_fallback_required"] == 4
    assert status["r4_8b_rows_ingested"] == 1
    assert status["r4_8b_production_inputs_staged"] == 1
    assert status["r4_8b_validated_source_manifests_written"] == 1
    assert status["r4_8b_forbidden_artifact_usage"] is False
    assert status["phase_7_8_blocked"] is True

    manifest_inventory = list(
        csv.DictReader(
            (tmp_path / "data" / "exports" / "validated_source_manifest_inventory_r4_8b.csv").open(
                encoding="utf-8"
            )
        )
    )
    assert len(manifest_inventory) == 1
    manifest_path = manifest_inventory[0]["manifest_path"]
    assert (tmp_path / manifest_path).exists()


def test_r48b_blocks_forbidden_artifact_paths(tmp_path: Path):
    script_rel = _make_script(
        tmp_path / "scripts" / "download_forbidden.py",
        "print('noop')\n",
    )

    readiness_rows = [
        {
            "priority": 1,
            "expected_input": "data/staging/processed/forbidden_summary.csv",
            "source_family": "src_forbidden",
            "readiness": "ready_for_execute_downloads",
            "next_action": "run",
            "reason": "",
            "producer_script": script_rel,
            "producer_script_exists": True,
            "required_env_vars": "",
            "credentials_present": True,
            "missing_env_vars": "",
            "target_output_path": "data/staging/processed/forbidden_summary.csv",
            "expected_schema_known": True,
            "validation_command": "python -c \"print('valid')\"",
            "has_validation_command": True,
            "manifest_path": "data/staging/processed/forbidden_summary.csv.manifest.json",
            "planning_manifest_present": True,
            "validated_manifest_present": False,
            "manual_path_required": False,
            "dropzone_path": "",
            "accepted_file_patterns": "",
            "forbidden_artifact_usage": True,
            "row_fabrication_policy": "FORBIDDEN_NO_SYNTHETIC_ROWS",
        }
    ]

    runner_rows = [
        {
            "priority": 1,
            "classification": "automated_backfill_available",
            "expected_input": "data/staging/processed/forbidden_summary.csv",
            "source_family": "src_forbidden",
            "likely_producer_script": script_rel,
            "target_output_path": "data/staging/processed/forbidden_summary.csv",
            "expected_schema": "award_id|recipient_name",
            "automated_command": f"python {script_rel}",
            "manual_steps": "",
            "requires_api_key": False,
            "required_env_vars": "",
            "requires_manual_export": False,
            "source_url_or_portal": "https://example.test/forbidden",
            "validation_command": "python -c \"print('validate ok')\"",
            "blocker_reason": "",
            "dry_run_command": f"DRY_RUN: python {script_rel}",
            "real_run_command_template": f"python {script_rel}",
            "forbidden_artifact_usage": True,
        }
    ]

    _bootstrap(tmp_path, readiness_rows, runner_rows)

    status = run_controlled_backfill_execution(tmp_path, execute_downloads=True)

    assert status["r4_8b_forbidden_artifact_usage"] is True
    assert status["r4_8b_gate_passed"] is False
    assert status["r4_8b_successful_sources"] == 0
    assert status["phase_7_8_blocked"] is True


def test_r48b_dry_run_mode_keeps_explicit_skips(tmp_path: Path):
    script_rel = _make_script(
        tmp_path / "scripts" / "download_dry.py",
        "print('dry')\n",
    )

    readiness_rows = [
        {
            "priority": 1,
            "expected_input": "data/staging/processed/dry.csv",
            "source_family": "src_dry",
            "readiness": "ready_for_execute_downloads",
            "next_action": "run",
            "reason": "",
            "producer_script": script_rel,
            "producer_script_exists": True,
            "required_env_vars": "",
            "credentials_present": True,
            "missing_env_vars": "",
            "target_output_path": "data/staging/processed/dry.csv",
            "expected_schema_known": True,
            "validation_command": "python -c \"print('valid')\"",
            "has_validation_command": True,
            "manifest_path": "data/staging/processed/dry.csv.manifest.json",
            "planning_manifest_present": True,
            "validated_manifest_present": False,
            "manual_path_required": False,
            "dropzone_path": "",
            "accepted_file_patterns": "",
            "forbidden_artifact_usage": False,
            "row_fabrication_policy": "FORBIDDEN_NO_SYNTHETIC_ROWS",
        }
    ]

    runner_rows = [
        {
            "priority": 1,
            "classification": "automated_backfill_available",
            "expected_input": "data/staging/processed/dry.csv",
            "source_family": "src_dry",
            "likely_producer_script": script_rel,
            "target_output_path": "data/staging/processed/dry.csv",
            "expected_schema": "award_id|recipient_name",
            "automated_command": f"python {script_rel}",
            "manual_steps": "",
            "requires_api_key": False,
            "required_env_vars": "",
            "requires_manual_export": False,
            "source_url_or_portal": "https://example.test/dry",
            "validation_command": "python -c \"print('validate ok')\"",
            "blocker_reason": "",
            "dry_run_command": f"DRY_RUN: python {script_rel}",
            "real_run_command_template": f"python {script_rel}",
            "forbidden_artifact_usage": False,
        }
    ]

    _bootstrap(tmp_path, readiness_rows, runner_rows)

    status = run_controlled_backfill_execution(tmp_path, execute_downloads=False)

    assert status["r4_8b_gate_passed"] is True
    assert status["r4_8b_attempted_sources"] == 0
    assert status["r4_8b_successful_sources"] == 0
    assert status["r4_8b_failed_sources"] == 1
    assert status["r4_8b_manual_fallback_required"] == 1
    assert status["r4_8b_rows_ingested"] == 0
    assert status["r4_8b_production_inputs_staged"] == 0
    assert status["phase_7_8_blocked"] is True
