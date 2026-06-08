"""Tests for highergov_mapper — deterministic HigherGov resource mapping."""

import pandas as pd

from scripts.highergov_mapper import (
    map_highergov_resource,
    validate_dates,
    validate_amounts,
    HIGHERGOV_MAPPINGS,
)


def test_validate_dates_with_valid_dates():
    """validate_dates returns 100% for all valid ISO dates."""
    df = pd.DataFrame({
        "date1": ["2024-01-15", "2024-02-20", "2024-03-10"],
        "date2": ["2023-12-01", "2023-11-15", "2023-10-20"],
    })
    
    results = validate_dates(df, ["date1", "date2"])
    assert results["date1"] == 100.0
    assert results["date2"] == 100.0


def test_validate_dates_with_mixed_formats():
    """validate_dates handles mixed date formats (COERCE mode)."""
    df = pd.DataFrame({
        "mixed_dates": ["2024-01-15", "invalid", "2024-03-10", None],
    })
    
    results = validate_dates(df, ["mixed_dates"])
    assert results["mixed_dates"] == 50.0


def test_validate_amounts_with_valid_numbers():
    """validate_amounts returns 100% for all valid numbers."""
    df = pd.DataFrame({
        "amount1": [1000.50, 2000.75, 3000.00],
        "amount2": ["1000", "2000", "3000"],
    })
    
    results = validate_amounts(df, ["amount1", "amount2"])
    assert results["amount1"] == 100.0
    assert results["amount2"] == 100.0


def test_map_highergov_opportunity_resource():
    """map_highergov_resource correctly maps opportunity resource."""
    df = pd.DataFrame({
        "opp_cat": ["cat1", "cat2"],
        "title": ["Opp1", "Opp2"],
        "posted_date": ["2024-01-15", "2024-02-20"],
        "due_date": ["2024-02-15", "2024-03-20"],
        "val_est_low": ["1000", "2000"],
        "val_est_high": ["5000", "10000"],
        "source_id": ["id1", "id2"],
    })
    
    mapped_df, validation = map_highergov_resource(df, "opportunity")
    
    assert validation["resource_type"] == "opportunity"
    assert validation["total_rows"] == 2
    assert pd.api.types.is_datetime64_any_dtype(mapped_df["posted_date"])
    assert pd.api.types.is_numeric_dtype(mapped_df["val_est_low"])


def test_map_highergov_contract_resource():
    """map_highergov_resource correctly maps contract resource."""
    df = pd.DataFrame({
        "piid": ["P1", "P2"],
        "agency_name": ["DOD", "DHS"],
        "contractor_name": ["Contractor A", "Contractor B"],
        "award_date": ["2024-01-10", "2024-02-15"],
        "contract_amount": ["100000", "200000"],
        "source_id": ["id1", "id2"],
    })
    
    mapped_df, validation = map_highergov_resource(df, "contract")
    assert validation["resource_type"] == "contract"
    assert validation["total_rows"] == 2


def test_map_highergov_unknown_resource_type():
    """map_highergov_resource handles unknown resource types gracefully."""
    df = pd.DataFrame({"col": [1, 2]})
    mapped_df, validation = map_highergov_resource(df, "unknown_type")
    assert validation == {}


def test_highergov_mappings_has_all_resource_types():
    """HIGHERGOV_MAPPINGS includes all expected resource types."""
    expected = {"opportunity", "idv", "contract", "subcontract"}
    assert expected.issubset(HIGHERGOV_MAPPINGS.keys())
