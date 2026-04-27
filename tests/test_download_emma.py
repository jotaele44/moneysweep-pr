"""Tests for download_emma — record normalization and underwriter extraction."""

import pandas as pd
import pytest

from scripts.download_emma import (
    _records_to_bonds_df,
    _records_to_underwriter_df,
    _build_underwriter_df_from_bonds,
    BOND_COLUMNS,
    UNDERWRITER_COLUMNS,
)


# ---------------------------------------------------------------------------
# _records_to_bonds_df
# ---------------------------------------------------------------------------

def test_empty_records_returns_empty_df():
    df = _records_to_bonds_df([])
    assert df.empty
    assert list(df.columns) == BOND_COLUMNS


def test_camel_case_fields_mapped():
    records = [{
        "Cusip":         "123456789",
        "issuerName":    "Puerto Rico Electric Power Authority",
        "maturityDate":  "2035-01-01",
        "parAmount":     "500000000",
        "couponRate":    "5.0",
        "saleType":      "negotiated",
        "taxStatus":     "tax-exempt",
    }]
    df = _records_to_bonds_df(records)
    assert df.iloc[0]["cusip"] == "123456789"
    assert "PUERTO RICO ELECTRIC POWER" in df.iloc[0]["issuer_normalized"].upper()
    assert df.iloc[0]["par_amount"] == "500000000"


def test_underwriter_field_extracted():
    records = [{
        "cusip":            "111222333",
        "issuerName":       "Commonwealth of Puerto Rico",
        "syndicateManager": "Goldman Sachs",
        "parAmount":        "1000000",
    }]
    df = _records_to_bonds_df(records)
    assert df.iloc[0]["underwriter_name"] == "Goldman Sachs"
    assert "GOLDMAN" in df.iloc[0]["underwriter_normalized"].upper()


def test_alternate_underwriter_field():
    records = [{"cusip": "AAA", "underwriterName": "Citigroup", "issuerName": "PREPA"}]
    df = _records_to_bonds_df(records)
    assert df.iloc[0]["underwriter_name"] == "Citigroup"


def test_issuer_state_defaults_to_pr():
    records = [{"cusip": "AAA", "issuerName": "Some Issuer"}]
    df = _records_to_bonds_df(records)
    assert df.iloc[0]["issuer_state"] == "PR"


def test_missing_columns_filled_empty():
    records = [{"cusip": "BBB"}]
    df = _records_to_bonds_df(records)
    assert set(BOND_COLUMNS).issubset(df.columns)
    assert df.iloc[0]["underwriter_name"] == ""


def test_multiple_records():
    records = [
        {"Cusip": "AAA", "issuerName": "PREPA", "parAmount": "100"},
        {"Cusip": "BBB", "issuerName": "PRASA", "parAmount": "200"},
    ]
    df = _records_to_bonds_df(records)
    assert len(df) == 2


# ---------------------------------------------------------------------------
# _records_to_underwriter_df (Path B stats records)
# ---------------------------------------------------------------------------

def test_underwriter_df_from_stats_empty():
    df = _records_to_underwriter_df([])
    assert df.empty
    assert list(df.columns) == UNDERWRITER_COLUMNS


def test_underwriter_df_from_stats_basic():
    records = [{
        "underwriterName": "Goldman Sachs",
        "totalParAmount":  "5000000000",
        "dealCount":       "12",
        "issuerCount":     "5",
        "firstIssueDate":  "2010-01-01",
        "lastIssueDate":   "2023-06-01",
    }]
    df = _records_to_underwriter_df(records)
    assert len(df) == 1
    assert df.iloc[0]["underwriter_name"] == "Goldman Sachs"
    assert "GOLDMAN" in df.iloc[0]["underwriter_normalized"].upper()
    assert df.iloc[0]["total_par_amount"] == pytest.approx(5_000_000_000.0)
    assert df.iloc[0]["deal_count"] == 12


def test_underwriter_df_filters_blank_names():
    records = [
        {"underwriterName": "Goldman", "totalParAmount": "1000"},
        {"underwriterName": "",        "totalParAmount": "2000"},
    ]
    df = _records_to_underwriter_df(records)
    assert len(df) == 1


def test_underwriter_df_sorted_descending_par():
    records = [
        {"underwriterName": "Small Firm", "totalParAmount": "100"},
        {"underwriterName": "Big Bank",   "totalParAmount": "9999"},
    ]
    df = _records_to_underwriter_df(records)
    assert df.iloc[0]["underwriter_name"] == "Big Bank"


# ---------------------------------------------------------------------------
# _build_underwriter_df_from_bonds (aggregation from bond rows)
# ---------------------------------------------------------------------------

def test_build_from_bonds_empty():
    df = _build_underwriter_df_from_bonds(pd.DataFrame(columns=BOND_COLUMNS))
    assert df.empty


def test_build_from_bonds_aggregates_correctly():
    df_bonds = pd.DataFrame({
        "cusip":                  ["A001", "A002", "A003"],
        "issuer_name":            ["PREPA", "PRASA", "PREPA"],
        "issuer_normalized":      ["PREPA", "PRASA", "PREPA"],
        "underwriter_name":       ["Goldman", "Goldman", "Citi"],
        "underwriter_normalized": ["GOLDMAN", "GOLDMAN", "CITI"],
        "par_amount":             ["500", "300", "200"],
        "issue_date":             ["2015-01-01", "2016-01-01", "2017-01-01"],
        **{c: [""] * 3 for c in BOND_COLUMNS
           if c not in ["cusip", "issuer_name", "issuer_normalized",
                        "underwriter_name", "underwriter_normalized",
                        "par_amount", "issue_date"]},
    })
    df_uw = _build_underwriter_df_from_bonds(df_bonds)
    assert len(df_uw) == 2
    goldman = df_uw[df_uw["underwriter_name"] == "Goldman"].iloc[0]
    assert goldman["total_par_amount"] == pytest.approx(800.0)
    assert goldman["deal_count"] == 2
    assert goldman["issuer_count"] == 2   # PREPA + PRASA


def test_build_from_bonds_skips_blank_underwriter():
    df_bonds = pd.DataFrame({
        "cusip":                  ["A001", "A002"],
        "issuer_name":            ["PREPA", "PRASA"],
        "issuer_normalized":      ["PREPA", "PRASA"],
        "underwriter_name":       ["",      "Goldman"],
        "underwriter_normalized": ["",      "GOLDMAN"],
        "par_amount":             ["100",   "200"],
        "issue_date":             ["2020-01-01", "2021-01-01"],
        **{c: [""] * 2 for c in BOND_COLUMNS
           if c not in ["cusip", "issuer_name", "issuer_normalized",
                        "underwriter_name", "underwriter_normalized",
                        "par_amount", "issue_date"]},
    })
    df_uw = _build_underwriter_df_from_bonds(df_bonds)
    assert len(df_uw) == 1
    assert df_uw.iloc[0]["underwriter_name"] == "Goldman"
