"""Tests for download_act60 — parse_records transform and KNOWN_ACT60_DATA fallback.

The live fetch needs egress (DDEC data.pr.gov API and Act 60 page). These tests
cover only the pure parse_records() transform, so they run fully offline.
"""

from __future__ import annotations

import pytest

from scripts.download_act60 import ACT60_COLUMNS, KNOWN_ACT60_DATA, parse_records


@pytest.mark.unit
def test_empty_records_returns_empty_df():
    df = parse_records([])
    assert df.empty
    assert list(df.columns) == ACT60_COLUMNS


@pytest.mark.unit
def test_canonical_keys_pass_through():
    records = [
        {
            "decree_id": "ACT60-2022-0001",
            "entity_name": "Luma Energy LLC",
            "entity_normalized": "LUMA ENERGY LLC",
            "decree_type": "Act 60",
            "effective_date": "2022-01-01",
            "expiry_date": "2037-01-01",
            "individual_flag": "0",
            "municipality": "San Juan",
            "industry_code": "2211",
            "source_url": "ddec_act60_registry",
        }
    ]
    df = parse_records(records)
    assert len(df) == 1
    assert list(df.columns) == ACT60_COLUMNS
    row = df.iloc[0]
    assert row["decree_id"] == "ACT60-2022-0001"
    assert row["decree_type"] == "Act 60"
    assert row["municipality"] == "San Juan"


@pytest.mark.unit
def test_entity_normalized_auto_computed():
    records = [{"entity_name": "Popular Inc", "source_url": "test"}]
    df = parse_records(records)
    assert df.iloc[0]["entity_normalized"] != ""


@pytest.mark.unit
def test_missing_columns_filled_with_empty_string():
    records = [{"entity_name": "Acme PR LLC"}]
    df = parse_records(records)
    assert list(df.columns) == ACT60_COLUMNS
    assert df.iloc[0]["municipality"] == ""
    assert df.iloc[0]["individual_flag"] == ""


@pytest.mark.unit
def test_known_act60_data_parses_cleanly():
    df = parse_records(KNOWN_ACT60_DATA)
    assert len(df) == len(KNOWN_ACT60_DATA)
    assert list(df.columns) == ACT60_COLUMNS
    types = set(df["decree_type"].tolist())
    assert {"Act 20", "Act 22", "Act 60"}.issubset(types)


@pytest.mark.unit
def test_multiple_records_all_rows_present():
    records = [
        {"entity_name": "Empresa A", "decree_type": "Act 60", "municipality": "Ponce"},
        {"entity_name": "Empresa B", "decree_type": "Act 20", "municipality": "Caguas"},
        {"entity_name": "Empresa C", "decree_type": "Act 22", "municipality": "Bayamon"},
    ]
    df = parse_records(records)
    assert len(df) == 3


@pytest.mark.unit
def test_spanish_column_names_mapped():
    records = [
        {
            "nombre": "Empresa XYZ",
            "municipio": "Mayaguez",
            "tipo_decreto": "Act 60",
            "fecha_efectiva": "2023-01-01",
        }
    ]
    df = parse_records(records)
    assert df.iloc[0]["entity_name"] == "Empresa XYZ"
    assert df.iloc[0]["municipality"] == "Mayaguez"
    assert df.iloc[0]["decree_type"] == "Act 60"
