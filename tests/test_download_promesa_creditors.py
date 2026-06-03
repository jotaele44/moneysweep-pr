"""Tests for download_promesa_creditors — parse_records transform and KNOWN_CREDITORS fallback.

The live fetch needs egress (Prime Clerk docket). These tests cover only the pure
parse_records() transform, so they run fully offline.
"""
from __future__ import annotations

import pytest

from scripts.download_promesa_creditors import KNOWN_CREDITORS, PROMESA_COLUMNS, parse_records


@pytest.mark.unit
def test_empty_records_returns_empty_df():
    df = parse_records([])
    assert df.empty
    assert list(df.columns) == PROMESA_COLUMNS


@pytest.mark.unit
def test_canonical_keys_pass_through():
    records = [{
        "creditor_name": "Aurelius Capital Management LP",
        "creditor_type": "hedge_fund",
        "bond_series": "GO",
        "claim_amount_original": 1_300_000_000,
        "recovery_amount": 585_000_000,
        "recovery_rate": 0.45,
        "sec_13f_flag": 1,
        "source_doc": "PROMESA Plan of Adjustment",
    }]
    df = parse_records(records)
    assert len(df) == 1
    assert list(df.columns) == PROMESA_COLUMNS
    row = df.iloc[0]
    assert row["creditor_name"] == "Aurelius Capital Management LP"
    assert row["creditor_type"] == "hedge_fund"
    assert row["bond_series"] == "GO"


@pytest.mark.unit
def test_creditor_normalized_auto_computed():
    records = [{"creditor_name": "Franklin Advisers Inc", "bond_series": "GO"}]
    df = parse_records(records)
    assert df.iloc[0]["creditor_normalized"] != ""


@pytest.mark.unit
def test_new_bond_cusip_defaults_to_empty():
    records = [{"creditor_name": "PIMCO", "bond_series": "GO"}]
    df = parse_records(records)
    assert df.iloc[0]["new_bond_cusip"] == ""


@pytest.mark.unit
def test_missing_columns_filled_with_empty_string():
    records = [{"creditor_name": "Test Fund LP"}]
    df = parse_records(records)
    assert list(df.columns) == PROMESA_COLUMNS
    assert df.iloc[0]["creditor_type"] == ""
    assert df.iloc[0]["bond_series"] == ""


@pytest.mark.unit
def test_known_creditors_parse_cleanly():
    df = parse_records(KNOWN_CREDITORS)
    assert len(df) == len(KNOWN_CREDITORS)
    assert list(df.columns) == PROMESA_COLUMNS
    types = set(df["creditor_type"].tolist())
    assert {"hedge_fund", "mutual_fund", "insurer", "bank"}.issubset(types)
    series = set(df["bond_series"].tolist())
    assert {"GO", "COFINA", "HTA", "PREPA", "ERS"}.issubset(series)


@pytest.mark.unit
def test_multiple_records_all_rows_present():
    records = [
        {"creditor_name": "Fund A", "bond_series": "GO", "creditor_type": "hedge_fund"},
        {"creditor_name": "Fund B", "bond_series": "COFINA", "creditor_type": "mutual_fund"},
        {"creditor_name": "Insurer C", "bond_series": "HTA", "creditor_type": "insurer"},
    ]
    df = parse_records(records)
    assert len(df) == 3
