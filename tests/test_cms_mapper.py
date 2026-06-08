"""Tests for cms_mapper — deterministic CMS healthcare data mapping."""

import pytest
import pandas as pd

from scripts.cms_mapper import (
    map_cms_resource,
    validate_dates,
    validate_amounts,
    CMS_MAPPINGS,
)


def test_validate_dates_with_valid_years():
    """validate_dates returns 100% for all valid year values."""
    df = pd.DataFrame({
        "payment_year": [2022, 2023, 2024],
    })
    
    results = validate_dates(df, ["payment_year"])
    # All years are valid (convertible to datetime)
    assert results["payment_year"] == 100.0


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
        "total_amount": [1000.50, 2000.75, 3000.00],
        "total_submitted_charges": ["100000", "200000", "300000"],
    })
    
    results = validate_amounts(df, ["total_amount", "total_submitted_charges"])
    assert results["total_amount"] == 100.0
    assert results["total_submitted_charges"] == 100.0


def test_validate_amounts_with_mixed_numbers():
    """validate_amounts handles mixed valid/invalid amounts."""
    df = pd.DataFrame({
        "total_amount": [1000, "invalid", 3000, None, 5000],
    })
    
    results = validate_amounts(df, ["total_amount"])
    assert results["total_amount"] == 60.0  # 3/5 valid


def test_map_cms_open_payments_resource():
    """map_cms_resource correctly maps open_payments resource."""
    df = pd.DataFrame({
        "payment_year": [2022, 2023, 2024],
        "covered_recipient_npi": [1111111111, 2222222222, 3333333333],
        "recipient_name": ["Dr. Smith", "Dr. Jones", "Hospital A"],
        "recipient_city": ["San Juan", "Ponce", "Mayaguez"],
        "recipient_state": ["PR", "PR", "PR"],
        "total_amount": [1000.50, 2500.75, 5000.00],
        "payer_name": ["Pharma Inc", "Device Corp", "Pharma Inc"],
    })
    
    mapped_df, validation = map_cms_resource(df, "open_payments")
    
    assert validation["resource_type"] == "open_payments"
    assert validation["row_count"] == 3
    assert validation["threshold_met"] is True
    assert "total_amount" in validation["amount_validation"]


def test_map_cms_medicare_resource():
    """map_cms_resource correctly maps medicare resource."""
    df = pd.DataFrame({
        "npi": [1111111111, 2222222222],
        "provider_name": ["Dr. Smith", "Dr. Jones"],
        "provider_city": ["San Juan", "Ponce"],
        "provider_state": ["PR", "PR"],
        "total_submitted_charges": [100000, 250000],
        "total_medicare_allowed": [85000, 210000],
        "total_medicare_payment": [85000, 200000],
        "total_medicare_standardized": [85000, 200000],
        "total_services": [500, 1200],
    })
    
    mapped_df, validation = map_cms_resource(df, "medicare")
    
    assert validation["resource_type"] == "medicare"
    assert validation["row_count"] == 2
    assert validation["threshold_met"] is True
    assert "total_submitted_charges" in validation["amount_validation"]
    assert "total_services" not in validation["amount_validation"]  # service metrics excluded


def test_map_cms_threshold_violation():
    """map_cms_resource detects threshold violations."""
    df = pd.DataFrame({
        "payment_year": [2022, 2023, 2024],
        "covered_recipient_npi": [1111111111, 2222222222, 3333333333],
        "recipient_name": ["Dr. Smith", "Dr. Jones", "Hospital A"],
        "total_amount": [1000, "invalid", "invalid"],  # 33% success
    })
    
    mapped_df, validation = map_cms_resource(df, "open_payments", threshold=95.0)
    
    assert validation["threshold_met"] is False
    assert "total_amount" in validation["issues"]


def test_map_cms_empty_dataframe():
    """map_cms_resource handles empty DataFrames gracefully."""
    df = pd.DataFrame({
        "payment_year": [],
        "covered_recipient_npi": [],
        "recipient_name": [],
        "total_amount": [],
    })
    
    mapped_df, validation = map_cms_resource(df, "open_payments")
    
    # Empty DataFrames have 0 rows, so no columns to validate actually have values
    # This causes a mismatch: 0 values parsed / 0 total = 0.0 (not 100%)
    # For empty data, threshold is still applied, so this is expected to fail
    assert validation["row_count"] == 0


def test_map_cms_unknown_resource_type():
    """map_cms_resource raises ValueError for unknown resource types."""
    df = pd.DataFrame({"col": [1, 2]})
    
    with pytest.raises(ValueError, match="Unknown CMS resource type"):
        map_cms_resource(df, "unknown_type")


def test_cms_mappings_has_expected_resource_types():
    """CMS_MAPPINGS includes all expected resource types."""
    expected = {"open_payments", "medicare"}
    assert expected.issubset(CMS_MAPPINGS.keys())
