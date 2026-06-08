"""Tests for fdic_mapper — deterministic FDIC bank data mapping."""

import pandas as pd

from scripts.fdic_mapper import (
    map_fdic_resource,
    validate_dates,
    validate_amounts,
    FDIC_MAPPINGS,
)


def test_validate_dates_with_valid_dates():
    """validate_dates returns 100% for all valid ISO dates."""
    df = pd.DataFrame(
        {
            "established_date": ["2024-01-15", "2024-02-20", "2024-03-10"],
            "end_date": ["2023-12-01", "2023-11-15", "2023-10-20"],
        }
    )

    results = validate_dates(df, ["established_date", "end_date"])
    assert results["established_date"] == 100.0
    assert results["end_date"] == 100.0


def test_validate_dates_with_mixed_formats():
    """validate_dates handles mixed date formats (COERCE mode)."""
    df = pd.DataFrame(
        {
            "mixed_dates": ["2024-01-15", "invalid", "2024-03-10", None],
        }
    )

    results = validate_dates(df, ["mixed_dates"])
    assert results["mixed_dates"] == 50.0


def test_validate_dates_missing_column():
    """validate_dates returns 0.0 for missing columns."""
    df = pd.DataFrame(
        {
            "some_col": [1, 2, 3],
        }
    )

    results = validate_dates(df, ["nonexistent_date"])
    assert results["nonexistent_date"] == 0.0


def test_validate_amounts_with_valid_numbers():
    """validate_amounts returns 100% for all valid numbers."""
    df = pd.DataFrame(
        {
            "total_assets": [1000000.50, 2000000.75, 3000000.00],
            "net_loans": ["1000", "2000", "3000"],
        }
    )

    results = validate_amounts(df, ["total_assets", "net_loans"])
    assert results["total_assets"] == 100.0
    assert results["net_loans"] == 100.0


def test_validate_amounts_with_mixed_numbers():
    """validate_amounts handles mixed valid/invalid amounts."""
    df = pd.DataFrame(
        {
            "total_assets": [1000000, "invalid", 3000000, None, 5000000],
        }
    )

    results = validate_amounts(df, ["total_assets"])
    assert results["total_assets"] == 60.0  # 3/5 valid


def test_map_fdic_institutions_resource():
    """map_fdic_resource correctly maps institutions resource."""
    df = pd.DataFrame(
        {
            "cert": [1001, 1002, 1003],
            "name": ["Bank A", "Bank B", "Bank C"],
            "established_date": ["2024-01-15", "2024-02-20", "2024-03-10"],
            "end_date": ["2025-01-15", "2025-02-20", "2025-03-15"],
            "latest_report_date": ["2024-12-31", "2024-12-31", "2024-12-31"],
            "total_assets": [1000000, 2000000, 3000000],
            "total_deposits": [900000, 1800000, 2700000],
            "net_loans": [500000, 1000000, 1500000],
            "securities": [100000, 200000, 300000],
            "net_income": [50000, 100000, 150000],
        }
    )

    mapped_df, validation = map_fdic_resource(df, "institutions")

    assert validation["resource_type"] == "institutions"
    assert validation["rows"] == 3
    assert validation["threshold_met"] is True
    assert "established_date" in validation["date_validation"]
    assert "total_assets" in validation["amount_validation"]


def test_map_fdic_financials_resource():
    """map_fdic_resource correctly maps financials resource."""
    df = pd.DataFrame(
        {
            "cert": [1001, 1002],
            "report_date": ["2024-01-15", "2024-02-20"],
            "report_year": [2024, 2024],
            "total_assets": [1000000, 2000000],
            "total_deposits": [900000, 1800000],
            "net_loans": [500000, 1000000],
            "securities": [100000, 200000],
            "net_income": ["100000", "200000"],
            "interest_income": ["50000", "100000"],
            "noninterest_income": [20000, 40000],
            "noninterest_expense": [30000, 60000],
            "loan_loss_provision": [10000, 20000],
            "net_chargeoffs": [5000, 10000],
            "total_equity": [200000, 400000],
            "total_liabilities": [800000, 1600000],
        }
    )

    mapped_df, validation = map_fdic_resource(df, "financials")

    assert validation["resource_type"] == "financials"
    assert validation["rows"] == 2
    assert "report_date" in validation["date_validation"]


def test_map_fdic_threshold_violation():
    """map_fdic_resource detects threshold violations."""
    df = pd.DataFrame(
        {
            "cert": [1001, 1002, 1003],
            "name": ["Bank A", "Bank B", "Bank C"],
            "established_date": ["2024-01-15", "invalid", "invalid"],  # 33% success
            "end_date": [None, None, None],
            "latest_report_date": ["2024-12-31", "2024-12-31", "2024-12-31"],
            "total_assets": [1000000, 2000000, 3000000],
            "total_deposits": [900000, 1800000, 2700000],
            "net_loans": [500000, 1000000, 1500000],
            "securities": [100000, 200000, 300000],
            "net_income": [50000, 100000, 150000],
        }
    )

    mapped_df, validation = map_fdic_resource(df, "institutions")

    assert validation["threshold_met"] is False
    assert "established_date" in validation["failed_dates"]


def test_map_fdic_unknown_resource_type():
    """map_fdic_resource handles unknown resource types gracefully."""
    df = pd.DataFrame({"col": [1, 2]})

    mapped_df, validation = map_fdic_resource(df, "unknown_type")
    assert "error" in validation


def test_fdic_mappings_has_expected_resource_types():
    """FDIC_MAPPINGS includes all expected resource types."""
    expected = {"institutions", "financials"}
    assert expected.issubset(FDIC_MAPPINGS.keys())
