"""Tests for download_rum_coverover — parse_records transform and KNOWN_COVEROVER fallback.

The live fetch needs egress (TTB + Treasury FiscalData API). These tests cover only
the pure parse_records() transform, so they run fully offline.
"""
from __future__ import annotations

import pytest

from scripts.download_rum_coverover import KNOWN_COVEROVER, RUM_COLUMNS, parse_records


@pytest.mark.unit
def test_empty_records_returns_empty_df():
    df = parse_records([])
    assert df.empty
    assert list(df.columns) == RUM_COLUMNS


@pytest.mark.unit
def test_canonical_keys_pass_through():
    records = [{
        "fiscal_year": "2023",
        "rum_gallons_pr": 35_000_000,
        "rum_proof_gallons_pr": 70_000_000,
        "excise_tax_rate_per_proof_gallon": 13.25,
        "excise_tax_estimated": 927_500_000,
        "coverover_amount_pr": 520_000_000,
        "allocation_prepa": 130_000_000,
        "allocation_hta": 65_000_000,
        "allocation_general_fund": 325_000_000,
        "source_doc": "AAFAF FY2023 Annual Report (estimated)",
    }]
    df = parse_records(records)
    assert len(df) == 1
    assert list(df.columns) == RUM_COLUMNS
    row = df.iloc[0]
    assert row["fiscal_year"] == "2023"
    assert row["coverover_amount_pr"] == 520_000_000
    assert row["allocation_prepa"] == 130_000_000


@pytest.mark.unit
def test_missing_columns_filled_with_empty_string():
    records = [{"fiscal_year": "2020", "coverover_amount_pr": 460_000_000}]
    df = parse_records(records)
    assert list(df.columns) == RUM_COLUMNS
    assert df.iloc[0]["allocation_prepa"] == ""
    assert df.iloc[0]["rum_gallons_pr"] == ""


@pytest.mark.unit
def test_known_coverover_parses_cleanly():
    df = parse_records(KNOWN_COVEROVER)
    assert len(df) == len(KNOWN_COVEROVER)
    assert list(df.columns) == RUM_COLUMNS
    years = set(df["fiscal_year"].astype(str).tolist())
    assert {"2017", "2018", "2019", "2020", "2021", "2022", "2023"}.issubset(years)


@pytest.mark.unit
def test_multiple_records_all_rows_present():
    records = [
        {"fiscal_year": "2021", "coverover_amount_pr": 490_000_000, "source_doc": "seed"},
        {"fiscal_year": "2022", "coverover_amount_pr": 505_000_000, "source_doc": "seed"},
        {"fiscal_year": "2023", "coverover_amount_pr": 520_000_000, "source_doc": "seed"},
    ]
    df = parse_records(records)
    assert len(df) == 3
    assert df["fiscal_year"].tolist() == ["2021", "2022", "2023"]
