from __future__ import annotations

import csv
from pathlib import Path

import pytest

from tools.build_automatable_execution_plan import EXPECTED_COLUMNS, build

pytestmark = pytest.mark.unit


def _write_matrix(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = sorted(EXPECTED_COLUMNS)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({name: row.get(name, "") for name in fieldnames})


def _row(
    source_id: str,
    *,
    automatable: bool = True,
    ready: bool = True,
    needs_key: str = "",
    trigger_type: str = "schedule",
    expected: int = 1,
    present: int = 0,
    required: bool = False,
) -> dict[str, str]:
    return {
        "source_id": source_id,
        "required": str(required),
        "family": "test",
        "update_cadence": "daily",
        "authentication": "none" if not needs_key else f"api_key:{needs_key}",
        "required_secret": needs_key,
        "trigger_type": trigger_type,
        "terminal": "False",
        "path_type": "api_producer" if automatable else "manual_export",
        "automatable": str(automatable),
        "ready": str(ready),
        "needs_key": needs_key,
        "has_adapter": "True",
        "producer_importable": "True",
        "producer_script": f"scripts/{source_id}.py",
        "expected_outputs_count": str(expected),
        "outputs_present_count": str(present),
        "min_rows": "1",
        "dropzone_path": "",
        "recommended_action": "test",
    }


def test_partition_arithmetic_and_tranches(tmp_path: Path) -> None:
    matrix = tmp_path / "matrix.csv"
    _write_matrix(
        matrix,
        [
            _row("scheduled", required=True),
            _row("derived", trigger_type="dependency"),
            _row("keyed", needs_key="FEC_API_KEY"),
            _row("manual", automatable=False, ready=False),
        ],
    )

    report = build(matrix)
    population = report["population"]
    assert population == {
        "total_sources": 4,
        "automatable_total": 3,
        "excluded_total": 1,
        "keyless_total": 2,
        "credential_gated_total": 1,
        "arithmetic": {
            "automatable_plus_excluded": 4,
            "keyless_plus_credential_gated": 3,
        },
    }
    assert report["required_keys"] == ["FEC_API_KEY"]
    assert report["required_automatable_source_ids"] == ["scheduled"]
    assert [row["source_id"] for row in report["tranches"]["keyless_schedule"]] == [
        "scheduled"
    ]
    assert [row["source_id"] for row in report["tranches"]["keyless_dependency"]] == [
        "derived"
    ]
    assert [row["source_id"] for row in report["tranches"]["credential_gated"]] == [
        "keyed"
    ]


def test_duplicate_source_ids_fail_closed(tmp_path: Path) -> None:
    matrix = tmp_path / "matrix.csv"
    _write_matrix(matrix, [_row("dup"), _row("dup")])
    with pytest.raises(RuntimeError, match="duplicate source IDs"):
        build(matrix)


def test_automatable_not_ready_fails_closed(tmp_path: Path) -> None:
    matrix = tmp_path / "matrix.csv"
    _write_matrix(matrix, [_row("broken", ready=False)])
    with pytest.raises(RuntimeError, match="automatable sources not ready"):
        build(matrix)


def test_output_overcount_fails_closed(tmp_path: Path) -> None:
    matrix = tmp_path / "matrix.csv"
    _write_matrix(matrix, [_row("bad", expected=1, present=2)])
    with pytest.raises(RuntimeError, match="outputs_present_count exceeds"):
        build(matrix)
