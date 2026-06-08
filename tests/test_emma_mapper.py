"""Tests for emma_mapper — deterministic EMMA bond data mapping."""

import pandas as pd

from scripts.emma_mapper import (
    map_emma_resource,
    validate_dates,
    validate_amounts,
    EMMA_MAPPINGS,
)


def test_validate_dates_with_valid_dates():
    """validate_dates returns 100% for all valid ISO dates."""
    df = pd.DataFrame({
        "issue_date": ["2024-01-15", "2024-02-20", "2024-03-10"],
        "maturity_date": ["2025-01-15", "2026-02-20", "2027-03-10"],
    })
    
    results = validate_dates(df, ["issue_date", "maturity_date"])
    assert results["issue_date"] == 100.0
    assert results["maturity_date"] == 100.0


def test_validate_dates_with_mixed_formats():
    """validate_dates handles mixed date formats (COERCE mode)."""
    df = pd.DataFrame({
        "mixed_dates": ["2024-01-15", "invalid", "2024-03-10", None],
    })
    
    results = validate_dates(df, ["mixed_dates"])
    assert results["mixed_dates"] == 50.0


def test_validate_dates_missing_column():
    """validate_dates returns 0.0 for missing columns."""
    df = pd.DataFrame({
        "some_col": [1, 2, 3],
    })
    
    results = validate_dates(df, ["nonexistent_date"])
    assert results["nonexistent_date"] == 0.0


def test_validate_amounts_with_valid_numbers():
    """validate_amounts returns 100% for all valid numbers."""
    df = pd.DataFrame({
        "par_amount": [1000000.50, 2000000.75, 3000000.00],
        "coupon_rate": ["2.5", "3.0", "3.5"],
    })
    
    results = validate_amounts(df, ["par_amount", "coupon_rate"])
    assert results["par_amount"] == 100.0
    assert results["coupon_rate"] == 100.0


def test_validate_amounts_with_mixed_numbers():
    """validate_amounts handles mixed valid/invalid amounts."""
    df = pd.DataFrame({
        "par_amount": [1000000, "invalid", 3000000, None, 5000000],
    })
    
    results = validate_amounts(df, ["par_amount"])
    assert results["par_amount"] == 60.0  # 3/5 valid


def test_map_emma_bonds_resource():
    """map_emma_resource correctly maps bonds resource."""
    df = pd.DataFrame({
        "cusip": ["CUSIP001", "CUSIP002", "CUSIP003"],
        "issuer_name": ["PR Gov", "PREPA", "PRASA"],
        "issue_date": ["2024-01-15", "2024-02-20", "2024-03-10"],
        "maturity_date": ["2025-01-15", "2026-02-20", "2027-03-10"],
        "par_amount": [1000000, 2000000, 3000000],
        "coupon_rate": [2.5, 3.0, 3.5],
    })
    
    mapped_df, validation = map_emma_resource(df, "bonds")
    
    assert validation["resource_type"] == "bonds"
    assert validation["rows"] == 3
    assert validation["threshold_met"] is True
    assert "issue_date" in validation["date_validation"]
    assert "par_amount" in validation["amount_validation"]


def test_map_emma_underwriters_resource():
    """map_emma_resource correctly maps underwriters resource."""
    df = pd.DataFrame({
        "firm_name": ["Firm A", "Firm B"],
        "deal_count": [10, 25],
        "issuer_count": [3, 5],
        "total_par_amount": [50000000, 100000000],
    })
    
    mapped_df, validation = map_emma_resource(df, "underwriters")
    
    assert validation["resource_type"] == "underwriters"
    assert validation["rows"] == 2
    assert "total_par_amount" in validation["amount_validation"]


def test_map_emma_threshold_violation():
    """map_emma_resource detects threshold violations."""
    df = pd.DataFrame({
        "cusip": ["CUSIP001", "CUSIP002", "CUSIP003"],
        "issuer_name": ["PR Gov", "PREPA", "PRASA"],
        "issue_date": ["2024-01-15", "invalid", "invalid"],  # 33% success
        "maturity_date": ["2025-01-15", "2026-02-20", "2027-03-10"],
        "par_amount": [1000000, 2000000, 3000000],
        "coupon_rate": [2.5, 3.0, 3.5],
    })
    
    mapped_df, validation = map_emma_resource(df, "bonds")
    
    assert validation["threshold_met"] is False
    assert "issue_date" in validation["failed_dates"]


def test_map_emma_unknown_resource_type():
    """map_emma_resource handles unknown resource types gracefully."""
    df = pd.DataFrame({"col": [1, 2]})
    
    mapped_df, validation = map_emma_resource(df, "unknown_type")
    assert "error" in validation


def test_emma_mappings_has_expected_resource_types():
    """EMMA_MAPPINGS includes all expected resource types."""
    expected = {"bonds", "underwriters"}
    assert expected.issubset(EMMA_MAPPINGS.keys())
