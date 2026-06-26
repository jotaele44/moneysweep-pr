"""Tests for R4 master input recovery + rebuild gate orchestration."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from moneysweep.validation.master_input_recovery import run_recovery_and_rebuild
from scripts import build_unified_master as bum


def _write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_r4_recovery_fail_closed_when_inputs_missing(tmp_path: Path):
    # Provide a build script manifest with required files that are absent.
    (tmp_path / "scripts").mkdir(parents=True, exist_ok=True)
    (tmp_path / "scripts" / "build_unified_master.py").write_text(
        "NEW_MASTERS = [('pr_grants_master.csv', 'grants')]\n"
        "EXPANSION_FILES = ['expansion_idv_indirect_pr.csv']\n",
        encoding="utf-8",
    )

    # Add a forbidden summary-like candidate to ensure stale-guard signals are visible.
    _write_csv(
        tmp_path / "data" / "staging" / "processed" / "pr_contracts_summary.csv",
        [{"contract_id": "S-1", "vendor_name": "Synthetic Vendor", "obligated_amount": "1"}],
        fieldnames=["contract_id", "vendor_name", "obligated_amount"],
    )
    _write_json(tmp_path / "data" / "exports" / "rebuild_status.json", {"phase_7_8_blocked": True})

    result = run_recovery_and_rebuild(tmp_path)

    assert result["r4_gate_passed"] is False
    assert result["phase_7_8_blocked"] is True
    assert result["missing_input_count"] >= 1
    assert result["rebuild_attempted"] is False

    assert (tmp_path / "data" / "exports" / "master_input_recovery_audit.csv").exists()
    assert (tmp_path / "data" / "exports" / "master_input_recovery_audit.json").exists()
    assert (tmp_path / "data" / "review_queue" / "master_input_recovery_blockers.csv").exists()


def test_r4_recovery_can_rebuild_with_full_gate_inputs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    # Keep build_unified_master scoped to the contracts core input only.
    monkeypatch.setattr(bum, "NEW_MASTERS", [])
    monkeypatch.setattr(bum, "EXPANSION_FILES", [])

    contracts = tmp_path / "data" / "staging" / "processed" / "pr_contracts_master.csv"
    _write_csv(
        contracts,
        [
            {
                "contract_id": "A-1",
                "vendor_name": "Acme LLC",
                "agency_name": "DOE",
                "award_date": "2024-10-15",
                "obligated_amount": "100",
                "pop_state": "PR",
                "fiscal_year": "2025",
                "source_file": "normalized_expansion_x.csv",
            }
        ],
        fieldnames=[
            "contract_id",
            "vendor_name",
            "agency_name",
            "award_date",
            "obligated_amount",
            "pop_state",
            "fiscal_year",
            "source_file",
        ],
    )

    # R5/R6 gates are outside R4 scope; pre-mark passed to validate unblock logic.
    _write_json(
        tmp_path / "data" / "exports" / "rebuild_status.json",
        {"r5_gate_passed": True, "r6_gate_passed": True},
    )

    result = run_recovery_and_rebuild(tmp_path)

    assert result["r4_gate_passed"] is True
    assert result["phase_7_8_blocked"] is False
    assert result["missing_input_count"] == 0
    assert result["forbidden_candidate_count"] == 0
    assert result["rebuild_succeeded"] is True
    assert result["rebuild_rows"] >= 1

    summary = json.loads(
        (tmp_path / "data" / "staging" / "processed" / "pr_all_awards_summary.json").read_text()
    )
    assert int(summary.get("total_rows", 0)) >= 1
    assert float(summary.get("source_lineage_coverage", 0.0)) > 0
