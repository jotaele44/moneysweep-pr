"""Tests for the COR3 producer's pure transform (scripts.download_cor3).

The live fetch endpoints are unverified guesses against recovery.pr.gov and need
network egress to confirm; these tests lock the transform + output contract so the
producer materializes the registry-declared output the moment it runs with egress.
"""
from __future__ import annotations

import pytest

from scripts.download_cor3 import OUTPUT_COLUMNS, parse_records

pytestmark = pytest.mark.unit


def test_parse_records_maps_to_canonical_columns():
    raw = [{"id": "P1", "applicant_name": "Muni A",
            "total_approved": "1,000", "total_disbursed": "500"}]
    df = parse_records(raw)
    assert list(df.columns) == OUTPUT_COLUMNS
    row = df.iloc[0]
    assert row["project_id"] == "P1"
    assert row["total_approved"] == 1000.0
    assert row["total_disbursed"] == 500.0
    assert row["disbursement_rate"] == 0.5  # 500 / 1000


def test_parse_records_handles_field_name_variants():
    # Different source key spellings must still map to the canonical schema.
    raw = [{"project_id": "P9", "applicant": "Muni Z",
            "approved_amount": "$2,000.00", "disbursed_amount": "1000"}]
    df = parse_records(raw)
    assert df.iloc[0]["total_approved"] == 2000.0
    assert df.iloc[0]["disbursement_rate"] == 0.5


def test_parse_records_dedupes_on_project_id_and_sorts_by_approved():
    raw = [
        {"id": "P1", "applicant_name": "A", "total_approved": "1000", "total_disbursed": "0"},
        {"id": "P1", "applicant_name": "A-dup", "total_approved": "1000", "total_disbursed": "0"},
        {"id": "P2", "applicant_name": "B", "total_approved": "5000", "total_disbursed": "0"},
    ]
    df = parse_records(raw)
    assert len(df) == 2                       # P1 deduped
    assert df.iloc[0]["project_id"] == "P2"   # highest total_approved first


def test_parse_records_zero_approved_gives_zero_rate():
    raw = [{"id": "P0", "applicant_name": "Z", "total_approved": "0", "total_disbursed": "0"}]
    assert parse_records(raw).iloc[0]["disbursement_rate"] == 0.0


def test_parse_records_empty_input_returns_empty_frame():
    df = parse_records([])
    assert df.empty
    assert list(df.columns) == OUTPUT_COLUMNS
