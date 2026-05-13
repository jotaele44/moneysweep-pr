import csv
import json
from pathlib import Path

from contract_sweeper.validation.controlled_backfill import run_controlled_backfill


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_r4_8b_classifies_terminal_statuses(tmp_path: Path) -> None:
    _write_csv(
        tmp_path / "data/review_queue/source_backfill_queue.csv",
        ["source_system", "priority", "expected_dataset", "reason", "owner"],
        [
            {"source_system": "sam", "priority": "1", "expected_dataset": "a", "reason": "missing", "owner": "ops"},
            {"source_system": "usaspending", "priority": "2", "expected_dataset": "b", "reason": "missing", "owner": "ops"},
            {"source_system": "lda", "priority": "3", "expected_dataset": "c", "reason": "missing", "owner": "ops"},
        ],
    )
    _write_csv(
        tmp_path / "data/review_queue/source_task_status.csv",
        ["source_system", "status", "rows_staged", "manifest_path", "schema_valid", "notes"],
        [
            {"source_system": "sam", "status": "success", "rows_staged": "15", "manifest_path": "data/staging/raw/sam/manifest.json", "schema_valid": "true", "notes": "ok"},
            {"source_system": "usaspending", "status": "no_data", "rows_staged": "0", "manifest_path": "", "schema_valid": "false", "notes": "none"},
            {"source_system": "lda", "status": "credential_failure", "rows_staged": "0", "manifest_path": "", "schema_valid": "false", "notes": "token"},
        ],
    )
    _write_json(tmp_path / "data/exports/rebuild_status.json", {"phase_7_8_blocked": True})

    status = run_controlled_backfill(tmp_path)

    assert status["r4_8b_attempted_sources"] == 3
    assert status["r4_8b_rows_ingested"] == 15
    assert status["r4_8b_terminal_status_counts"]["success"] == 1
    assert status["r4_8b_terminal_status_counts"]["no_data"] == 1
    assert status["r4_8b_terminal_status_counts"]["credential_failure"] == 1
    assert status["row_fabrication_policy"] == "FORBIDDEN_NO_SYNTHETIC_ROWS"

    results = tmp_path / "data/exports/controlled_backfill_execution_results_r4_8b.csv"
    assert results.exists()

    with results.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))

    assert len(rows) == 3
    assert {row["status"] for row in rows} == {"success", "no_data", "credential_failure"}
