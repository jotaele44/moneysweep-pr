"""Tests for R4.6 backfill execution plan generation."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from contract_sweeper.validation.backfill_execution_plan import run_plan


def _write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_r46_plan_uses_manual_queue_without_fabrication(tmp_path: Path):
    rows = []
    for i in range(1, 22):
        rows.append(
            {
                "priority": i,
                "expected_input": f"data/staging/processed/input_{i}.csv",
                "dataset_label": f"dataset_{i}",
                "input_group": "canonical_master",
                "reason": "missing",
                "recommended_action": "download",
                "producer_scripts": "scripts/download_dummy.py|scripts/config.py",
            }
        )

    _write_csv(
        tmp_path / "data" / "review_queue" / "manual_source_download_queue.csv",
        rows,
        [
            "priority",
            "expected_input",
            "dataset_label",
            "input_group",
            "reason",
            "recommended_action",
            "producer_scripts",
        ],
    )
    _write_json(tmp_path / "data" / "exports" / "rebuild_status.json", {"phase_7_8_blocked": True})

    result = run_plan(tmp_path)

    assert result["plan_row_count"] == 21
    assert result["phase_7_8_blocked"] is True
    assert result["row_fabrication_policy"] == "FORBIDDEN_NO_SYNTHETIC_ROWS"

    plan_csv = tmp_path / "data" / "exports" / "backfill_execution_plan_r4_6.csv"
    plan_rows = list(csv.DictReader(plan_csv.open("r", encoding="utf-8")))
    assert len(plan_rows) == 21
    assert all(r["row_fabrication_policy"] == "FORBIDDEN_NO_SYNTHETIC_ROWS" for r in plan_rows)


def test_r46_updates_rebuild_status(tmp_path: Path):
    _write_csv(
        tmp_path / "data" / "review_queue" / "manual_source_download_queue.csv",
        [
            {
                "priority": 1,
                "expected_input": "data/staging/processed/pr_contracts_master.csv",
                "dataset_label": "contracts",
                "input_group": "core",
                "reason": "missing",
                "recommended_action": "rebuild",
                "producer_scripts": "scripts/deduplicate_master.py",
            }
        ],
        [
            "priority",
            "expected_input",
            "dataset_label",
            "input_group",
            "reason",
            "recommended_action",
            "producer_scripts",
        ],
    )
    _write_json(tmp_path / "data" / "exports" / "rebuild_status.json", {})

    run_plan(tmp_path)

    status = json.loads((tmp_path / "data" / "exports" / "rebuild_status.json").read_text())
    assert status["phase_7_8_blocked"] is True
    assert "r4_6_generated_at" in status
    assert "r4_6_outputs" in status
