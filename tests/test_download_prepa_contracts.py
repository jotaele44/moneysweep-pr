"""Tests for download_prepa_contracts — parse_records transform and KNOWN_CONTRACTS fallback.

The live fetch needs egress (FOMB + P3 Authority pages). These tests cover only
the pure parse_records() transform, so they run fully offline.
"""
from __future__ import annotations

import pandas as pd
import pytest

from scripts.download_prepa_contracts import KNOWN_CONTRACTS, PREPA_COLUMNS, parse_records


@pytest.mark.unit
def test_empty_records_returns_empty_df():
    df = parse_records([])
    assert df.empty
    assert list(df.columns) == PREPA_COLUMNS


@pytest.mark.unit
def test_canonical_keys_pass_through():
    records = [{
        "contract_id": "LUMA-OM-2021",
        "vendor_name": "Luma Energy LLC",
        "contract_type": "O&M",
        "contract_value": 1_500_000_000,
        "start_date": "2021-06-01",
        "end_date": "2036-06-01",
        "status": "Active",
        "description": "15-year T&D operation and maintenance agreement",
        "source_doc": "FOMB PREPA Transformation",
        "source_url": "https://oversightboard.pr.gov/prepa/",
    }]
    df = parse_records(records)
    assert len(df) == 1
    assert list(df.columns) == PREPA_COLUMNS
    row = df.iloc[0]
    assert row["contract_id"] == "LUMA-OM-2021"
    assert row["contract_type"] == "O&M"
    assert row["status"] == "Active"


@pytest.mark.unit
def test_vendor_normalized_auto_computed():
    records = [{"contract_id": "X", "vendor_name": "Cobra Acquisitions LLC"}]
    df = parse_records(records)
    assert df.iloc[0]["vendor_normalized"] == "COBRA ACQUISITIONS"


@pytest.mark.unit
def test_missing_columns_filled_with_empty_string():
    records = [{"contract_id": "Y", "vendor_name": "Whitefish Energy Holdings LLC"}]
    df = parse_records(records)
    assert list(df.columns) == PREPA_COLUMNS
    assert df.iloc[0]["contract_type"] == ""
    assert df.iloc[0]["description"] == ""


@pytest.mark.unit
def test_known_contracts_parse_cleanly():
    df = parse_records(KNOWN_CONTRACTS)
    assert len(df) == len(KNOWN_CONTRACTS)
    assert list(df.columns) == PREPA_COLUMNS
    statuses = set(df["status"].tolist())
    assert {"Active", "Terminated", "Completed"}.issubset(statuses)


@pytest.mark.unit
def test_multiple_records_all_rows_present():
    records = [
        {"contract_id": "A", "vendor_name": "Fluor Corp", "status": "Completed"},
        {"contract_id": "B", "vendor_name": "MasTec Inc", "status": "Completed"},
        {"contract_id": "C", "vendor_name": "Luma Energy LLC", "status": "Active"},
    ]
    df = parse_records(records)
    assert len(df) == 3
    assert df["contract_id"].tolist() == ["A", "B", "C"]
