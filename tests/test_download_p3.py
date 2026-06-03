"""Tests for download_p3 — parse_records transform and KNOWN_P3_PROJECTS fallback.

The live fetch needs egress (P3 Authority portal + AAFAF P3 page). These tests
cover only the pure parse_records() transform, so they run fully offline.
"""
from __future__ import annotations

import pandas as pd
import pytest

from scripts.download_p3 import KNOWN_P3_PROJECTS, P3_COLUMNS, parse_records


@pytest.mark.unit
def test_empty_records_returns_empty_df():
    df = parse_records([])
    assert df.empty
    assert list(df.columns) == P3_COLUMNS


@pytest.mark.unit
def test_canonical_keys_pass_through():
    records = [{
        "project_id": "P3-001",
        "project_name": "Luis Muñoz Marín Airport",
        "sector": "transport",
        "concessionaire_name": "Aerostar Airport Holdings LLC",
        "concessionaire_normalized": "",
        "contract_value": "2400000000",
        "term_years": "40",
        "award_date": "2013-02-27",
        "financial_close_date": "2013-02-27",
        "federal_funding_flag": "Y",
        "status": "active",
        "source_doc": "known_p3_seed",
    }]
    df = parse_records(records)
    assert len(df) == 1
    assert list(df.columns) == P3_COLUMNS
    row = df.iloc[0]
    assert row["project_id"] == "P3-001"
    assert row["sector"] == "transport"
    assert row["contract_value"] == "2400000000"


@pytest.mark.unit
def test_concessionaire_normalized_auto_filled():
    records = [{"project_id": "P3-X", "concessionaire_name": "Luma Energy LLC"}]
    df = parse_records(records)
    assert df.iloc[0]["concessionaire_normalized"] == "LUMA ENERGY"


@pytest.mark.unit
def test_missing_columns_filled_with_empty_string():
    records = [{"project_id": "P3-Y", "project_name": "Test Project"}]
    df = parse_records(records)
    assert list(df.columns) == P3_COLUMNS
    assert df.iloc[0]["sector"] == ""
    assert df.iloc[0]["status"] == ""


@pytest.mark.unit
def test_known_p3_projects_parse_cleanly():
    df = parse_records(KNOWN_P3_PROJECTS)
    assert len(df) == len(KNOWN_P3_PROJECTS)
    assert list(df.columns) == P3_COLUMNS
    sectors = set(df["sector"].tolist())
    assert {"transport", "water", "energy"}.issubset(sectors)


@pytest.mark.unit
def test_multiple_records_all_rows_present():
    records = [
        {"project_id": "P3-A", "project_name": "Alpha", "concessionaire_name": "Acme Corp"},
        {"project_id": "P3-B", "project_name": "Beta", "concessionaire_name": "Beta Inc"},
        {"project_id": "P3-C", "project_name": "Gamma", "concessionaire_name": ""},
    ]
    df = parse_records(records)
    assert len(df) == 3
    assert df["project_id"].tolist() == ["P3-A", "P3-B", "P3-C"]
