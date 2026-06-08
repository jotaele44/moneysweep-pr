"""Tests for download_active_contractors — parse_records transform.

The live fetch needs egress to PR government contractor APIs (asg.pr.gov,
consultacontratos.ocpr.gov.pr, hacienda.pr.gov). These tests cover only the
pure parse_records() transform, so they run fully offline.
"""

from __future__ import annotations

import pandas as pd
import pytest

from scripts.download_active_contractors import CONTRACTOR_COLUMNS, parse_records


@pytest.mark.unit
def test_none_returns_empty_with_columns():
    df = parse_records(None)
    assert df.empty
    assert list(df.columns) == CONTRACTOR_COLUMNS


@pytest.mark.unit
def test_empty_df_returns_empty_with_columns():
    df = parse_records(pd.DataFrame())
    assert df.empty
    assert list(df.columns) == CONTRACTOR_COLUMNS


@pytest.mark.unit
def test_vendor_name_column_mapped():
    raw = pd.DataFrame(
        [
            {
                "Vendor Name": "Island Logistics LLC",
                "Registration ID": "ASG-0042",
                "Municipality": "Caguas",
                "Status": "Active",
            }
        ]
    )
    df = parse_records(raw, "api")
    assert len(df) == 1
    assert list(df.columns) == CONTRACTOR_COLUMNS
    assert df.iloc[0]["entity_name"] == "Island Logistics LLC"
    assert df.iloc[0]["registration_id"] == "ASG-0042"


@pytest.mark.unit
def test_suplidor_column_mapped():
    raw = pd.DataFrame(
        [
            {
                "Suplidor": "Constructora Caribe LLC",
                "Municipio": "Bayamón",
                "Estado": "Activo",
            }
        ]
    )
    df = parse_records(raw, "suplidores_page")
    assert df.iloc[0]["entity_name"] == "Constructora Caribe LLC"
    assert df.iloc[0]["municipality"] == "Bayamón"


@pytest.mark.unit
def test_entity_normalized_strips_suffixes():
    raw = pd.DataFrame([{"Vendor Name": "Tech Solutions Corp"}])
    df = parse_records(raw)
    assert df.iloc[0]["entity_normalized"] == "TECH SOLUTIONS"


@pytest.mark.unit
def test_missing_columns_filled_empty_string():
    raw = pd.DataFrame([{"Vendor Name": "Solo Vendor"}])
    df = parse_records(raw)
    assert list(df.columns) == CONTRACTOR_COLUMNS
    assert df.iloc[0]["naics_code"] == ""
    assert df.iloc[0]["expiry_date"] == ""


@pytest.mark.unit
def test_multiple_rows_all_present():
    rows = [
        {"Vendor Name": "Alpha Services LLC", "Status": "Active"},
        {"Vendor Name": "Beta Supplies Inc", "Status": "Active"},
    ]
    df = parse_records(pd.DataFrame(rows))
    assert len(df) == 2
    assert df["entity_name"].tolist() == ["Alpha Services LLC", "Beta Supplies Inc"]
