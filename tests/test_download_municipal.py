"""Tests for download_municipal — parse_records transform and KNOWN_MUNICIPAL_DATA fallback.

The live fetch needs egress (USASpending API). These tests cover only the pure
parse_records() transform, so they run fully offline.
"""

from __future__ import annotations

import pytest

from scripts.download_municipal import KNOWN_MUNICIPAL_DATA, OUTPUT_COLUMNS, parse_records


@pytest.mark.unit
def test_empty_records_returns_empty_df():
    df = parse_records([])
    assert df.empty
    assert list(df.columns) == OUTPUT_COLUMNS


@pytest.mark.unit
def test_canonical_keys_pass_through():
    records = [
        {
            "municipality": "San Juan",
            "fiscal_year": "2023",
            "federal_awards_count": "4200",
            "federal_awards_obligated": "1850000000",
            "federal_transfers_per_capita": "5900",
            "data_source": "usaspending_known_seed",
        }
    ]
    df = parse_records(records)
    assert len(df) == 1
    assert list(df.columns) == OUTPUT_COLUMNS
    row = df.iloc[0]
    assert row["municipality"] == "San Juan"
    assert row["fiscal_year"] == "2023"
    assert float(row["federal_awards_obligated"]) == 1_850_000_000.0


@pytest.mark.unit
def test_missing_columns_filled_with_empty_string():
    records = [{"municipality": "Ponce"}]
    df = parse_records(records)
    assert list(df.columns) == OUTPUT_COLUMNS
    assert df.iloc[0]["fiscal_year"] == ""
    assert df.iloc[0]["data_source"] == ""


@pytest.mark.unit
def test_known_municipal_data_parses_cleanly():
    df = parse_records(KNOWN_MUNICIPAL_DATA)
    assert len(df) == len(KNOWN_MUNICIPAL_DATA)
    assert list(df.columns) == OUTPUT_COLUMNS
    municipalities = set(df["municipality"].tolist())
    assert {"San Juan", "Bayamon", "Ponce"}.issubset(municipalities)


@pytest.mark.unit
def test_multiple_records_all_rows_present():
    records = [
        {"municipality": "Caguas", "fiscal_year": "2022", "federal_awards_obligated": "230000000"},
        {"municipality": "Humacao", "fiscal_year": "2022", "federal_awards_obligated": "85000000"},
        {
            "municipality": "Mayaguez",
            "fiscal_year": "2022",
            "federal_awards_obligated": "120000000",
        },
    ]
    df = parse_records(records)
    assert len(df) == 3
    assert df["municipality"].tolist() == ["Caguas", "Humacao", "Mayaguez"]


@pytest.mark.unit
def test_obligated_coerced_to_numeric():
    records = [
        {"municipality": "Arecibo", "federal_awards_obligated": "not_a_number"},
        {"municipality": "Dorado", "federal_awards_obligated": "500000"},
    ]
    df = parse_records(records)
    assert df.iloc[0]["federal_awards_obligated"] == 0.0
    assert df.iloc[1]["federal_awards_obligated"] == 500_000.0
