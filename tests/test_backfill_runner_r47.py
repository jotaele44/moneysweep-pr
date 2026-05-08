"""Tests for R4.7 backfill runner and import slot planning."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from contract_sweeper.pipeline.backfill_runner import generate_backfill_runner_plan


def _write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_build_unified(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "CANONICAL_COLUMNS = ['award_id','recipient_name','source_dataset']\n"
        "EXPANSION_RENAME = {'Award ID':'award_id','Recipient Name':'recipient_name'}\n",
        encoding="utf-8",
    )


def test_r47_generates_runner_manifest_and_import_slots(tmp_path: Path):
    _write_build_unified(tmp_path / "scripts" / "build_unified_master.py")
    _write_json(tmp_path / "data" / "exports" / "rebuild_status.json", {})
    _write_json(tmp_path / "data" / "exports" / "backfill_execution_plan_r4_6_status.json", {"r4_6_gate_passed": True})

    # Scripts: one actionable, one non-actionable, one missing.
    (tmp_path / "scripts" / "download_grants.py").write_text("import os\nos.getenv('GRANTS_API_KEY')\n", encoding="utf-8")
    (tmp_path / "scripts" / "config.py").write_text("CONFIG = True\n", encoding="utf-8")

    plan_rows = [
        {
            "priority": 1,
            "expected_input": "data/staging/processed/pr_grants_master.csv",
            "dataset_label": "grants",
            "input_group": "canonical_master",
            "producer_script": "scripts/download_grants.py",
            "output_path": "data/staging/processed/pr_grants_master.csv",
        },
        {
            "priority": 2,
            "expected_input": "data/staging/expansion/expansion_idv_indirect_pr.csv",
            "dataset_label": "contracts",
            "input_group": "expansion",
            "producer_script": "scripts/config.py",
            "output_path": "data/staging/expansion/expansion_idv_indirect_pr.csv",
        },
        {
            "priority": 3,
            "expected_input": "data/staging/processed/pr_unknown_master.csv",
            "dataset_label": "unknown",
            "input_group": "canonical_master",
            "producer_script": "scripts/download_missing.py",
            "output_path": "data/staging/processed/pr_unknown_master.csv",
        },
    ]
    _write_csv(
        tmp_path / "data" / "exports" / "backfill_execution_plan_r4_6.csv",
        plan_rows,
        ["priority", "expected_input", "dataset_label", "input_group", "producer_script", "output_path"],
    )

    result = generate_backfill_runner_plan(tmp_path, dry_run=True, execute_downloads=False)

    assert result["counts"]["total_sources"] == 3
    assert result["counts"]["automated_sources"] >= 1
    assert result["phase_7_8_blocked"] is True
    assert result["execute_downloads_default"] is False

    manifest_rows = list(csv.DictReader((tmp_path / "data" / "exports" / "backfill_runner_manifest_r4_7.csv").open("r", encoding="utf-8")))
    assert len(manifest_rows) == 3
    assert all(row["validation_command"] for row in manifest_rows)
    assert all(row["target_output_path"] for row in manifest_rows)

    # Non-automated rows get manual slots.
    import_slots = list(csv.DictReader((tmp_path / "data" / "exports" / "import_slots_r4_7.csv").open("r", encoding="utf-8")))
    assert len(import_slots) >= 1


def test_r47_detects_forbidden_expected_input(tmp_path: Path):
    _write_build_unified(tmp_path / "scripts" / "build_unified_master.py")
    _write_json(tmp_path / "data" / "exports" / "rebuild_status.json", {})
    _write_json(tmp_path / "data" / "exports" / "backfill_execution_plan_r4_6_status.json", {})
    (tmp_path / "scripts" / "download_grants.py").write_text("print('ok')\n", encoding="utf-8")

    _write_csv(
        tmp_path / "data" / "exports" / "backfill_execution_plan_r4_6.csv",
        [
            {
                "priority": 1,
                "expected_input": "data/staging/processed/pr_grants_summary.csv",
                "dataset_label": "grants",
                "input_group": "canonical_master",
                "producer_script": "scripts/download_grants.py",
                "output_path": "data/staging/processed/pr_grants_summary.csv",
            }
        ],
        ["priority", "expected_input", "dataset_label", "input_group", "producer_script", "output_path"],
    )

    result = generate_backfill_runner_plan(tmp_path, dry_run=True, execute_downloads=False)
    assert result["forbidden_artifact_usage"] is True
    assert result["r4_7_gate_passed"] is False
