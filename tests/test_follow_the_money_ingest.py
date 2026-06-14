"""Tests for the Follow the Money ingester (scripts.ingest_follow_the_money).

Covers the pure transform functions and the full drop-file -> processed-CSV chain
(3 output files: SF-133 budget execution, municipal bridge, facility matches). The
ingester reads operator-delivered CSV exports from data/raw/follow_the_money/ — no
network code — so all tests run fully offline.

The Epstein PR-case bank-wire records that previously also lived in this dropzone
were separated into the epstein_pr_case watchlist (see test_epstein_watchlist.py);
this ingester no longer reads or produces them.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pandas as pd
import pytest

from scripts.ingest_follow_the_money import (
    SF133_OUTPUT_COLUMNS,
    _build_sf133,
    run,
)


class _NullLogger:
    def info(self, *a, **k):
        pass

    def warning(self, *a, **k):
        pass


# ---------------------------------------------------------------------------
# Unit: _build_sf133 pivot
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_build_sf133_produces_canonical_schema():
    df = pd.DataFrame(
        {
            "report_year": ["2024", "2024"],
            "agency": ["HUD", "HUD"],
            "account": ["Community Dev", "Community Dev"],
            "omb_account": ["86-0162", "86-0162"],
            "total_annual": ["1000000", "750000"],
            "is_obligation": ["False", "True"],
        }
    )
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
    df = pd.DataFrame(
        {
            "report_year": ["2023", "2023"],
            "agency": ["FEMA", "FEMA"],
            "account": ["DRF", "DRF"],
            "omb_account": ["70-0702", "70-0702"],
            "total_annual": ["500", "200"],
            "is_obligation": ["1", "0"],
        }
    )
    out = _build_sf133(df, _NullLogger())
    row = out.iloc[0]
    assert float(row["obligations"]) == pytest.approx(500)
    assert float(row["budget_authority"]) == pytest.approx(200)


# ---------------------------------------------------------------------------
# Integration: full drop-file -> 3 output CSVs
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
def test_run_with_sf133_file_writes_three_outputs(tmp_path: Path):
    drop = tmp_path / "data" / "raw" / "follow_the_money"
    drop.mkdir(parents=True)

    # Minimal SF-133 file
    with (drop / "funding_flows_sf133.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(
            ["report_year", "agency", "account", "omb_account", "total_annual", "is_obligation"]
        )
        w.writerow(["2024", "HUD", "CDBG", "86-0162", "1000000", "False"])
        w.writerow(["2024", "HUD", "CDBG", "86-0162", "750000", "True"])

    result = run(root=tmp_path)
    assert result["rows"] == 1
    assert result["status"] == "OK"
    assert set(result["outputs"]) == {
        "pr_sf133_budget_execution.csv",
        "pr_ftm_municipal_bridge.csv",
        "pr_ftm_facility_matches.csv",
    }

    out_dir = tmp_path / "data" / "staging" / "processed"
    sf133 = out_dir / "pr_sf133_budget_execution.csv"
    muni = out_dir / "pr_ftm_municipal_bridge.csv"
    fac = out_dir / "pr_ftm_facility_matches.csv"

    for p in (sf133, muni, fac):
        assert p.exists(), f"Expected output missing: {p.name}"

    # No Epstein wire-ledger output is produced anymore.
    assert not (out_dir / "pr_ftm_wire_ledger.csv").exists()

    # SF-133 output has canonical columns
    rows = list(csv.DictReader(sf133.open()))
    assert list(rows[0].keys()) == SF133_OUTPUT_COLUMNS


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
