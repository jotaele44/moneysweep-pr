"""Tests for ingest_active_contractors — parse_records transform.

The live ingest needs a file placed in data/raw/Active Contractor Listing/.
These tests cover only the pure parse_records() transform, so they run offline.
"""
from __future__ import annotations

import pandas as pd
import pytest

from scripts.ingest_active_contractors import CONTRACTOR_COLUMNS, parse_records


@pytest.mark.unit
def test_empty_df_returns_empty_with_columns():
    df = parse_records(pd.DataFrame())
    assert df.empty
    assert list(df.columns) == CONTRACTOR_COLUMNS


@pytest.mark.unit
def test_english_column_names_pass_through():
    raw = pd.DataFrame([{
        "Name": "Acme Construction Corp",
        "Registro": "REG-001",
        "Registration Date": "2022-01-15",
        "Expiry Date": "2024-01-15",
        "Type": "General Contractor",
        "NAICS": "2361",
        "Municipality": "San Juan",
        "Status": "Active",
    }])
    df = parse_records(raw, "test.csv")
    assert len(df) == 1
    assert list(df.columns) == CONTRACTOR_COLUMNS
    assert df.iloc[0]["entity_name"] == "Acme Construction Corp"
    assert df.iloc[0]["registration_id"] == "REG-001"
    assert df.iloc[0]["municipality"] == "San Juan"
    assert df.iloc[0]["source_file"] == "test.csv"


@pytest.mark.unit
def test_spanish_column_names_mapped():
    raw = pd.DataFrame([{
        "Nombre": "Constructora PR LLC",
        "Registro": "PR-2020-0001",
        "Municipio": "Ponce",
        "Estado": "Activo",
    }])
    df = parse_records(raw, "spanish.csv")
    assert len(df) == 1
    assert df.iloc[0]["entity_name"] == "Constructora PR LLC"
    assert df.iloc[0]["registration_id"] == "PR-2020-0001"
    assert df.iloc[0]["municipality"] == "Ponce"
    assert df.iloc[0]["status"] == "Activo"


@pytest.mark.unit
def test_entity_normalized_computed():
    raw = pd.DataFrame([{"Name": "Caribbean Builders Inc"}])
    df = parse_records(raw)
    assert df.iloc[0]["entity_normalized"] == "CARIBBEAN BUILDERS"


@pytest.mark.unit
def test_missing_columns_filled_empty_string():
    raw = pd.DataFrame([{"Name": "Empresa XYZ"}])
    df = parse_records(raw)
    assert list(df.columns) == CONTRACTOR_COLUMNS
    assert df.iloc[0]["naics_code"] == ""
    assert df.iloc[0]["registration_id"] == ""


@pytest.mark.unit
def test_multiple_rows_all_present():
    rows = [
        {"Name": "Vendor A", "Status": "Active"},
        {"Name": "Vendor B", "Status": "Inactive"},
        {"Name": "Vendor C", "Status": "Active"},
    ]
    df = parse_records(pd.DataFrame(rows))
    assert len(df) == 3
    assert df["entity_name"].tolist() == ["Vendor A", "Vendor B", "Vendor C"]


@pytest.mark.unit
def test_blank_entity_name_rows_filtered():
    raw = pd.DataFrame([
        {"Name": "Real Company LLC"},
        {"Name": ""},
        {"Name": "   "},
    ])
    df = parse_records(raw)
    assert len(df) == 1
    assert df.iloc[0]["entity_name"] == "Real Company LLC"
