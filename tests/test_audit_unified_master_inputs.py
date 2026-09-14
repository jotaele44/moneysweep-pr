from __future__ import annotations

import csv
from pathlib import Path

import pytest

from tools.audit_unified_master_inputs import (
    AuditError,
    CANONICAL,
    CONTRACTS,
    EXPANSIONS,
    OPTIONAL,
    OUTPUT,
    audit,
)

pytestmark = pytest.mark.unit


def _csv(root: Path, rel: str, rows: list[str] | None = None) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("id\n" + "\n".join(rows or ["1"]) + "\n", encoding="utf-8")


def _all_required(root: Path) -> None:
    _csv(root, CONTRACTS)
    for name in CANONICAL:
        rel = f"data/staging/processed/{name}"
        if rel not in OPTIONAL:
            _csv(root, rel)
    for rel in EXPANSIONS:
        _csv(root, rel)


def _status(root: Path, value: str = "partially_materialized") -> Path:
    path = root / "reports/source_registry_status.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["source_id", "pipeline_status"])
        writer.writerow(["usaspending_prime", value])
    return path


def test_historical_report_cannot_manufacture_missing_bytes(tmp_path: Path) -> None:
    report = audit(tmp_path, _status(tmp_path, "fully_materialized"))
    assert report["state"] == "BLOCKED_INPUT_CORPUS"
    assert report["reported_source_status"] == "fully_materialized"
    assert report["reported_presence_is_byte_evidence"] is False
    assert CONTRACTS in report["missing_required"]


def test_ready_only_when_every_required_byte_validates(tmp_path: Path) -> None:
    _all_required(tmp_path)
    report = audit(tmp_path, _status(tmp_path))
    assert report["state"] == "READY_TO_BUILD"
    assert report["missing_required"] == []
    assert report["invalid_inputs"] == []
    assert report["builder_contract"]["required_input_count"] == 20
    assert report["builder_contract"]["optional_input_count"] == 1


def test_optional_hud_master_does_not_block(tmp_path: Path) -> None:
    _all_required(tmp_path)
    assert not (tmp_path / "data/staging/processed/pr_hud_master.csv").exists()
    assert audit(tmp_path)["state"] == "READY_TO_BUILD"


def test_one_missing_expansion_fails_closed(tmp_path: Path) -> None:
    _all_required(tmp_path)
    (tmp_path / EXPANSIONS[0]).unlink()
    report = audit(tmp_path)
    assert report["state"] == "BLOCKED_INPUT_CORPUS"
    assert report["missing_required"] == [EXPANSIONS[0]]


def test_existing_output_does_not_override_missing_inputs(tmp_path: Path) -> None:
    _csv(tmp_path, OUTPUT)
    report = audit(tmp_path)
    assert report["output"]["byte_present"] is True
    assert report["state"] == "BLOCKED_INPUT_CORPUS"


def test_ragged_csv_is_invalid(tmp_path: Path) -> None:
    _all_required(tmp_path)
    path = tmp_path / CONTRACTS
    path.write_text("id,name\n1\n", encoding="utf-8")
    report = audit(tmp_path)
    assert CONTRACTS in report["invalid_inputs"]
    assert report["state"] == "BLOCKED_INPUT_CORPUS"


def test_symlink_input_rejected(tmp_path: Path) -> None:
    _all_required(tmp_path)
    target = tmp_path / "elsewhere.csv"
    target.write_text("id\n1\n", encoding="utf-8")
    path = tmp_path / CONTRACTS
    path.unlink()
    path.symlink_to(target)
    report = audit(tmp_path)
    row = next(item for item in report["inputs"] if item["path"] == CONTRACTS)
    assert row["state"] == "INVALID"
    assert "symlink" in row["error"]


def test_duplicate_headers_fail_closed(tmp_path: Path) -> None:
    _all_required(tmp_path)
    (tmp_path / CONTRACTS).write_text("id,id\n1,2\n", encoding="utf-8")
    report = audit(tmp_path)
    assert CONTRACTS in report["invalid_inputs"]


def test_audit_never_grants_production_eligibility(tmp_path: Path) -> None:
    _all_required(tmp_path)
    report = audit(tmp_path)
    assert report["state"] == "READY_TO_BUILD"
    assert report["production_eligible"] is False
