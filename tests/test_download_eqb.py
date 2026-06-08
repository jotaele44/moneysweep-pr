"""Tests for download_eqb — parse_records transform.

The live fetch needs egress (EPA ECHO ICIS ZIP downloads from echo.epa.gov).
These tests cover only the pure parse_records() transform, so they run fully
offline.
"""

from __future__ import annotations

import pandas as pd
import pytest

from scripts.download_eqb import OUTPUT_COLUMNS, parse_records


@pytest.mark.unit
def test_empty_df_returns_empty_df():
    df = parse_records(pd.DataFrame())
    assert df.empty
    assert list(df.columns) == OUTPUT_COLUMNS


@pytest.mark.unit
def test_none_returns_empty_df():
    df = parse_records(None)
    assert df.empty
    assert list(df.columns) == OUTPUT_COLUMNS


@pytest.mark.unit
def test_air_permit_canonical_columns():
    raw = pd.DataFrame(
        [
            {
                "AIR_ID": "PR-AIR-001",
                "FAC_NAME": "Acme Puerto Rico Plant",
                "PERMIT_ISSUE_DATE": "2020-01-15",
                "PERMIT_EXPIRATION_DATE": "2025-01-14",
                "VIOL_CNT": "3",
                "INSP_CNT": "5",
                "FAC_STATE": "PR",
            }
        ]
    )
    df = parse_records(raw, permit_type="air")
    assert len(df) == 1
    assert list(df.columns) == OUTPUT_COLUMNS
    row = df.iloc[0]
    assert row["permit_id"] == "PR-AIR-001"
    assert row["permit_type"] == "air"
    assert row["violation_count"] == 3
    assert row["inspection_count"] == 5
    assert row["state"] == "PR"


@pytest.mark.unit
def test_water_permit_canonical_columns():
    raw = pd.DataFrame(
        [
            {
                "NPDES_ID": "PRG110001",
                "FAC_NAME": "San Juan WWTP",
                "PERMIT_ISSUE_DATE": "2019-06-01",
                "PERMIT_EXPIRATION_DATE": "2024-05-31",
                "VIOL_CNT": "0",
                "INSP_CNT": "2",
                "FAC_STATE": "PR",
            }
        ]
    )
    df = parse_records(raw, permit_type="water")
    assert len(df) == 1
    row = df.iloc[0]
    assert row["permit_id"] == "PRG110001"
    assert row["permit_type"] == "water"
    assert row["violation_count"] == 0


@pytest.mark.unit
def test_multiple_rows_all_present():
    raw = pd.DataFrame(
        [
            {
                "AIR_ID": "PR-001",
                "FAC_NAME": "Plant A",
                "VIOL_CNT": "1",
                "INSP_CNT": "2",
                "FAC_STATE": "PR",
            },
            {
                "AIR_ID": "PR-002",
                "FAC_NAME": "Plant B",
                "VIOL_CNT": "0",
                "INSP_CNT": "1",
                "FAC_STATE": "PR",
            },
            {
                "AIR_ID": "PR-003",
                "FAC_NAME": "Plant C",
                "VIOL_CNT": "5",
                "INSP_CNT": "3",
                "FAC_STATE": "PR",
            },
        ]
    )
    df = parse_records(raw, "air")
    assert len(df) == 3
    assert list(df.columns) == OUTPUT_COLUMNS


@pytest.mark.unit
def test_missing_columns_fall_back_gracefully():
    raw = pd.DataFrame([{"REGISTRY_ID": "PR-REG-001"}])
    df = parse_records(raw, "air")
    assert len(df) == 1
    assert df.iloc[0]["permit_id"] == "PR-REG-001"
    assert df.iloc[0]["facility_name"] == ""
    assert df.iloc[0]["violation_count"] == 0
    assert df.iloc[0]["state"] == "PR"
