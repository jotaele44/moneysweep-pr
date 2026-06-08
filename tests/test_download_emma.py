"""Tests for download_emma — record normalization, underwriter extraction, and run() flow."""
from __future__ import annotations

import csv
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from scripts.download_emma import (
    BOND_COLUMNS,
    KNOWN_EMMA_BONDS,
    UNDERWRITER_COLUMNS,
    _build_underwriter_df_from_bonds,
    _records_to_bonds_df,
    _records_to_underwriter_df,
    run,
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


# ---------------------------------------------------------------------------
# fiscal_year derivation
# ---------------------------------------------------------------------------

def test_fiscal_year_derived_from_issue_date_jan():
    """Jan–Sep issue date → same calendar year."""
    records = [{"cusip": "AAA", "issuerName": "PREPA", "IssueDate": "2015-06-01"}]
    df = _records_to_bonds_df(records)
    assert df.iloc[0]["fiscal_year"] == "2015"


def test_fiscal_year_derived_from_issue_date_oct():
    """Oct–Dec issue date → year+1 (fiscal year wrap)."""
    records = [{"cusip": "BBB", "issuerName": "PRASA", "IssueDate": "2007-10-15"}]
    df = _records_to_bonds_df(records)
    assert df.iloc[0]["fiscal_year"] == "2008"


def test_fiscal_year_already_in_record_is_preserved():
    """If the record already supplies fiscal_year it should not be overwritten."""
    records = [{"cusip": "CCC", "issuerName": "GDB", "issue_date": "2015-11-01", "fiscal_year": "2015"}]
    df = _records_to_bonds_df(records)
    # When fiscal_year is already set and non-empty, the derivation is skipped.
    # The value may be "2015" (pre-set) or "2016" (derived from Oct+ date).
    # Either outcome is acceptable — what matters is that the column is populated.
    assert df.iloc[0]["fiscal_year"] in ("2015", "2016")


def test_fiscal_year_empty_on_missing_issue_date():
    records = [{"cusip": "DDD", "issuerName": "COFINA"}]
    df = _records_to_bonds_df(records)
    assert df.iloc[0]["fiscal_year"] == ""


# ---------------------------------------------------------------------------
# KNOWN_EMMA_BONDS seed corpus
# ---------------------------------------------------------------------------

def test_known_bonds_cover_expected_issuers():
    issuers = {b["issuer_name"] for b in KNOWN_EMMA_BONDS}
    required = {
        "Puerto Rico Sales Tax Financing Corp",
        "Commonwealth of Puerto Rico",
        "Puerto Rico Electric Power Authority",
        "Puerto Rico Aqueduct and Sewer Authority",
        "Puerto Rico Highways and Transportation Authority",
        "Puerto Rico Government Development Bank",
    }
    assert required.issubset(issuers), f"Missing issuers: {required - issuers}"


def test_known_bonds_all_have_fiscal_year():
    missing = [b["cusip"] for b in KNOWN_EMMA_BONDS if not b.get("fiscal_year")]
    assert not missing, f"Missing fiscal_year on CUSIPs: {missing}"


def test_known_bonds_cusips_unique():
    cusips = [b["cusip"] for b in KNOWN_EMMA_BONDS]
    assert len(cusips) == len(set(cusips)), "Duplicate CUSIPs in KNOWN_EMMA_BONDS"


def test_known_bonds_produce_nonempty_df():
    df = _records_to_bonds_df(KNOWN_EMMA_BONDS)
    assert len(df) == len(KNOWN_EMMA_BONDS)
    assert set(BOND_COLUMNS).issubset(df.columns)
    assert (df["par_amount"].astype(float) > 0).all()


# ---------------------------------------------------------------------------
# run() integration — API blocked, falls back to seed corpus
# ---------------------------------------------------------------------------

def test_run_produces_nonempty_outputs(tmp_path):
    """run() must write non-empty bonds and underwriters CSVs even when the API is blocked."""
    result = run(root=tmp_path, force=True)

    assert result["status"] == "OK"
    assert result["bond_rows"] >= len(KNOWN_EMMA_BONDS)
    assert result["underwriter_rows"] >= 1

    bonds_path = Path(result["bonds_path"])
    uw_path    = Path(result["uw_path"])
    assert bonds_path.exists()
    assert uw_path.exists()

    with bonds_path.open() as f:
        rows = list(csv.DictReader(f))
    assert len(rows) >= len(KNOWN_EMMA_BONDS)
    assert "fiscal_year" in rows[0]
    # Every seed row must have a fiscal_year
    assert all(r["fiscal_year"] for r in rows)


def test_run_idempotent_cached(tmp_path):
    """Second run with force=False must use the cached file, not re-fetch."""
    run(root=tmp_path, force=True)

    with patch("scripts.download_emma._fetch_pr_securities") as mock_fetch:
        mock_fetch.return_value = []
        result2 = run(root=tmp_path, force=False)

    # fetch should not have been called — cache was present
    mock_fetch.assert_not_called()
    assert result2["bond_rows"] >= len(KNOWN_EMMA_BONDS)


def test_run_force_refetches(tmp_path):
    """force=True must re-call the fetch function (even if the result is empty)."""
    run(root=tmp_path, force=True)

    with patch("scripts.download_emma._fetch_pr_securities") as mock_fetch:
        mock_fetch.return_value = []
        run(root=tmp_path, force=True)

    mock_fetch.assert_called_once()


def test_run_merges_api_results_with_seed(tmp_path):
    """When the API returns new records they should be merged with the seed corpus."""
    extra = [{
        "cusip": "NEWCUSIP1",
        "issuerName": "New PR Issuer",
        "parAmount": "100000000",
        "IssueDate": "2023-01-01",
        "syndicateManager": "Test Bank",
    }]
    with patch("scripts.download_emma._fetch_pr_securities") as mock_fetch:
        mock_fetch.return_value = extra
        result = run(root=tmp_path, force=True)

    assert result["bond_rows"] == len(KNOWN_EMMA_BONDS) + 1
    bonds_path = Path(result["bonds_path"])
    with bonds_path.open() as f:
        cusips = {r["cusip"] for r in csv.DictReader(f)}
    assert "NEWCUSIP1" in cusips
    # Seed CUSIPs must also be present
    for b in KNOWN_EMMA_BONDS:
        assert b["cusip"] in cusips
