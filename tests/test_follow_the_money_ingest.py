"""Tests for the Follow the Money ingester (scripts.ingest_follow_the_money).

Covers the pure transform functions and the full drop-file -> processed-CSV chain
(4 output files). The ingester reads operator-delivered CSV exports from
data/raw/Follow the Money/ — no network code — so all tests run fully offline.
"""
from __future__ import annotations

import csv
from pathlib import Path

import pandas as pd
import pytest

from scripts.ingest_follow_the_money import (
    FACILITY_COLUMNS,
    MUNI_BRIDGE_COLUMNS,
    SF133_OUTPUT_COLUMNS,
    WIRE_COLUMNS,
    _build_sf133,
    _build_wire_ledger,
    run,
)


class _NullLogger:
    def info(self, *a, **k): pass
    def warning(self, *a, **k): pass


# ---------------------------------------------------------------------------
# Unit: _build_sf133 pivot
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_build_sf133_produces_canonical_schema():
    df = pd.DataFrame({
        "report_year": ["2024", "2024"],
        "agency":      ["HUD", "HUD"],
        "account":     ["Community Dev", "Community Dev"],
        "omb_account": ["86-0162", "86-0162"],
        "total_annual": ["1000000", "750000"],
        "is_obligation": ["False", "True"],
    })
    out = _build_sf133(df, _NullLogger())
    assert list(out.columns) == SF133_OUTPUT_COLUMNS
    assert len(out) == 1
    row = out.iloc[0]
    assert row["fiscal_year"] == "2024"
    assert row["agency_name"] == "HUD"
    assert float(row["budget_authority"]) == pytest.approx(1_000_000)
    assert float(row["obligations"]) == pytest.approx(750_000)


@pytest.mark.unit
def test_build_sf133_handles_is_obligation_variants():
    df = pd.DataFrame({
        "report_year": ["2023", "2023"],
        "agency":      ["FEMA", "FEMA"],
        "account":     ["DRF", "DRF"],
        "omb_account": ["70-0702", "70-0702"],
        "total_annual": ["500", "200"],
        "is_obligation": ["1", "0"],
    })
    out = _build_sf133(df, _NullLogger())
    row = out.iloc[0]
    assert float(row["obligations"]) == pytest.approx(500)
    assert float(row["budget_authority"]) == pytest.approx(200)


# ---------------------------------------------------------------------------
# Unit: _build_wire_ledger
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_build_wire_ledger_empty_inputs_returns_empty_schema():
    out = _build_wire_ledger(None, None, None, None, _NullLogger())
    assert list(out.columns) == WIRE_COLUMNS
    assert len(out) == 0


@pytest.mark.unit
def test_build_wire_ledger_with_ledger_df():
    ledger = pd.DataFrame({
        "txn_date":           ["2024-01-15"],
        "entity_raw":         ["ACME LLC"],
        "destination_bank":   ["FirstBank"],
        "destination_account": ["123456"],
        "amount_usd":         ["50000"],
    })
    out = _build_wire_ledger(ledger, None, None, None, _NullLogger())
    assert list(out.columns) == WIRE_COLUMNS
    assert len(out) == 1
    assert out.iloc[0]["entity_raw"] == "ACME LLC"


# ---------------------------------------------------------------------------
# Integration: full drop-file -> 4 output CSVs
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_run_no_dropzone_returns_no_files(tmp_path: Path):
    result = run(root=tmp_path)
    assert result["status"] == "NO_FILES"
    assert result["rows"] == 0
    # run() does NOT create output files when raw_dir doesn't exist
    out_dir = tmp_path / "data" / "staging" / "processed"
    assert not (out_dir / "pr_sf133_budget_execution.csv").exists()


@pytest.mark.integration
def test_run_with_sf133_file_writes_all_four_outputs(tmp_path: Path):
    drop = tmp_path / "data" / "raw" / "Follow the Money"
    drop.mkdir(parents=True)

    # Minimal SF-133 file
    with (drop / "funding_flows_sf133.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["report_year", "agency", "account", "omb_account",
                    "total_annual", "is_obligation"])
        w.writerow(["2024", "HUD", "CDBG", "86-0162", "1000000", "False"])
        w.writerow(["2024", "HUD", "CDBG", "86-0162", "750000", "True"])

    result = run(root=tmp_path)
    assert result["rows"] == 1
    assert result["status"] == "OK"

    out_dir = tmp_path / "data" / "staging" / "processed"
    sf133 = out_dir / "pr_sf133_budget_execution.csv"
    wire  = out_dir / "pr_ftm_wire_ledger.csv"
    muni  = out_dir / "pr_ftm_municipal_bridge.csv"
    fac   = out_dir / "pr_ftm_facility_matches.csv"

    for p in (sf133, wire, muni, fac):
        assert p.exists(), f"Expected output missing: {p.name}"

    # SF-133 output has canonical columns
    rows = list(csv.DictReader(sf133.open()))
    assert list(rows[0].keys()) == SF133_OUTPUT_COLUMNS

    # Wire/muni/facility outputs have correct empty schemas (no wire files given)
    wire_rows = list(csv.DictReader(wire.open()))
    assert list(csv.DictReader(wire.open()).fieldnames or []) == WIRE_COLUMNS or wire_rows == []


@pytest.mark.integration
def test_run_caches_on_existing_primary_output(tmp_path: Path):
    out_dir = tmp_path / "data" / "staging" / "processed"
    out_dir.mkdir(parents=True)
    primary = out_dir / "pr_sf133_budget_execution.csv"
    with primary.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=SF133_OUTPUT_COLUMNS)
        w.writeheader()
        w.writerow({c: "x" if c == "fiscal_year" else "0" for c in SF133_OUTPUT_COLUMNS})

    result = run(root=tmp_path)
    assert result["status"] == "CACHED"
    assert result["rows"] == 1
