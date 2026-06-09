"""Deterministic column mapping for HigherGov API resources.

Maps HigherGov columns (opportunity, idv, contract, subcontract) to standard
normalized contract columns with validation of date/amount parsing.
"""

from __future__ import annotations
import pandas as pd
import logging

logger = logging.getLogger(__name__)

# Deterministic mappings per resource type
HIGHERGOV_MAPPINGS: dict = {
    "opportunity": {
        "description": "Municipal opportunities (small businesses, contracts)",
        "date_cols": ["posted_date", "due_date", "captured_date"],
        "amount_cols": ["val_est_low", "val_est_high"],
        "id_cols": ["source_id", "opp_key"],
        "agency_col": None,  # Not typically present in opportunities
        "vendor_col": None,
    },
    "idv": {
        "description": "Indefinite Delivery Vehicles (IDVs) - call orders",
        "date_cols": ["last_modified_date", "captured_date"],
        "amount_cols": ["val_est_low", "val_est_high"],
        "id_cols": ["source_id", "opp_key"],
        "agency_col": "agency_name",
        "vendor_col": "contractor_name",
    },
    "contract": {
        "description": "Prime awards (direct contracts)",
        "date_cols": ["last_modified_date", "award_date"],
        "amount_cols": ["contract_amount", "base_amount"],
        "id_cols": ["source_id", "piid"],
        "agency_col": "agency_name",
        "vendor_col": "contractor_name",
    },
    "subcontract": {
        "description": "Subcontract awards",
        "date_cols": ["last_modified_date", "award_date"],
        "amount_cols": ["subcontract_amount"],
        "id_cols": ["source_id", "piid"],
        "agency_col": "agency_name",
        "vendor_col": "contractor_name",
    },
}


def validate_dates(df: pd.DataFrame, date_cols: list) -> dict:
    """Validate date parsing for specified columns.

    Returns dict with column names as keys and parse success % as values.
    """
    results = {}
    for col in date_cols:
        if col not in df.columns:
            results[col] = 0.0
            continue

        # Try to parse as datetime
        try:
            parsed = pd.to_datetime(df[col], errors="coerce")
            success_pct = (parsed.notna().sum() / len(df)) * 100 if len(df) > 0 else 0.0
            results[col] = success_pct
        except Exception as e:
            logger.warning(f"Failed to validate date column {col}: {e}")
            results[col] = 0.0

    return results


def validate_amounts(df: pd.DataFrame, amount_cols: list) -> dict:
    """Validate numeric parsing for specified columns.

    Returns dict with column names as keys and numeric success % as values.
    """
    results = {}
    for col in amount_cols:
        if col not in df.columns:
            results[col] = 0.0
            continue

        try:
            # Try to convert to numeric
            numeric = pd.to_numeric(df[col], errors="coerce")
            success_pct = (numeric.notna().sum() / len(df)) * 100 if len(df) > 0 else 0.0
            results[col] = success_pct
        except Exception as e:
            logger.warning(f"Failed to validate amount column {col}: {e}")
            results[col] = 0.0

    return results


def map_highergov_resource(df: pd.DataFrame, resource_type: str) -> tuple[pd.DataFrame, dict]:
    """Apply deterministic mapping for a HigherGov resource type.

    Args:
        df: Input DataFrame from HigherGov API
        resource_type: One of 'opportunity', 'idv', 'contract', 'subcontract'

    Returns:
        Tuple of (mapped_df, validation_results)
    """
    if resource_type not in HIGHERGOV_MAPPINGS:
        logger.error(f"Unknown resource type: {resource_type}")
        return df, {}

    mapping = HIGHERGOV_MAPPINGS[resource_type]
    validation: dict = {
        "resource_type": resource_type,
        "total_rows": len(df),
        "dates": {},
        "amounts": {},
    }

    # Validate dates
    validation["dates"] = validate_dates(df, mapping["date_cols"])

    # Validate amounts
    validation["amounts"] = validate_amounts(df, mapping["amount_cols"])

    # Perform date conversions
    for col in mapping["date_cols"]:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")

    # Perform amount conversions
    for col in mapping["amount_cols"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # Log summary
    min_date_pct = min(validation["dates"].values()) if validation["dates"] else 0
    min_amount_pct = min(validation["amounts"].values()) if validation["amounts"] else 0

    logger.info(
        f"HigherGov {resource_type}: {len(df)} rows, "
        f"min date parse {min_date_pct:.1f}%, min amount parse {min_amount_pct:.1f}%"
    )

    return df, validation
