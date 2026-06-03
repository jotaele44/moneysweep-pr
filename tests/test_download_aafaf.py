"""Tests for download_aafaf — parse_records transform and KNOWN_AAFAF_DATA fallback.

The live fetch needs egress (AAFAF reports index + CKAN API). These tests cover
only the pure parse_records() transform, so they run fully offline.
"""
from __future__ import annotations

import pandas as pd
import pytest

from scripts.download_aafaf import AAFAF_COLUMNS, KNOWN_AAFAF_DATA, parse_records


@pytest.mark.unit
def test_empty_records_returns_empty_df():
    df = parse_records([])
    assert df.empty
    assert list(df.columns) == AAFAF_COLUMNS


@pytest.mark.unit
def test_canonical_keys_pass_through():
    records = [{
        "fiscal_year": "2024",
        "month": "january",
        "report_type": "general_fund",
        "revenue_category": "total_revenues",
        "revenue_amount": "13100000000",
        "expenditure_category": "total_expenditures",
        "expenditure_amount": "11600000000",
        "cash_balance": "500000000",
        "source_doc": "fomb_fiscal_plan_2024",
    }]
    df = parse_records(records)
    assert len(df) == 1
    assert list(df.columns) == AAFAF_COLUMNS
    row = df.iloc[0]
    assert row["fiscal_year"] == "2024"
    assert row["revenue_amount"] == "13100000000"
    assert row["source_doc"] == "fomb_fiscal_plan_2024"


@pytest.mark.unit
def test_missing_columns_filled_with_empty_string():
    records = [{"fiscal_year": "2023", "revenue_amount": "12000000000"}]
    df = parse_records(records)
    assert list(df.columns) == AAFAF_COLUMNS
    assert df.iloc[0]["month"] == ""
    assert df.iloc[0]["cash_balance"] == ""


@pytest.mark.unit
def test_known_aafaf_data_parses_cleanly():
    df = parse_records(KNOWN_AAFAF_DATA)
    assert len(df) == len(KNOWN_AAFAF_DATA)
    assert list(df.columns) == AAFAF_COLUMNS
    years = set(df["fiscal_year"].tolist())
    assert {"2021", "2022", "2023", "2024"}.issubset(years)


@pytest.mark.unit
def test_multiple_records_all_rows_present():
    records = [
        {"fiscal_year": "2022", "revenue_amount": "11800000000"},
        {"fiscal_year": "2023", "revenue_amount": "12400000000"},
        {"fiscal_year": "2024", "revenue_amount": "13100000000"},
    ]
    df = parse_records(records)
    assert len(df) == 3
    assert df["fiscal_year"].tolist() == ["2022", "2023", "2024"]
