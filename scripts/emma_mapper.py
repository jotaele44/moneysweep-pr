"""Deterministic column mapping for EMMA municipal bond data.

Maps EMMA bond and underwriter columns to standard normalized format
with validation of date/amount parsing.
"""

from __future__ import annotations
import pandas as pd
import logging

logger = logging.getLogger(__name__)

# Deterministic mappings for EMMA data
EMMA_MAPPINGS = {
    "bonds": {
        "description": "MSRB EMMA municipal bond securities",
        "date_cols": ["issue_date", "maturity_date"],
        "amount_cols": ["par_amount", "coupon_rate"],
        "id_cols": ["cusip", "isin"],
        "issuer_col": "issuer_name",
    },
    "underwriters": {
        "description": "EMMA underwriter aggregations by firm",
        "date_cols": ["first_issue_date", "last_issue_date"],
        "amount_cols": ["total_par_amount"],
        "id_cols": ["underwriter_name"],
        "count_cols": ["deal_count", "issuer_count"],
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

        try:
            parsed = pd.to_datetime(df[col], errors="coerce")
            success_count = parsed.notna().sum()
            total_count = len(df)
            results[col] = (success_count / total_count * 100) if total_count > 0 else 0.0
        except Exception as e:
            logger.warning(f"Failed to validate dates in {col}: {e}")
            results[col] = 0.0

    return results


def validate_amounts(df: pd.DataFrame, amount_cols: list) -> dict:
    """Validate numeric amount parsing for specified columns.

    Returns dict with column names as keys and parse success % as values.
    """
    results = {}
    for col in amount_cols:
        if col not in df.columns:
            results[col] = 0.0
            continue

        try:
            parsed = pd.to_numeric(df[col], errors="coerce")
            success_count = parsed.notna().sum()
            total_count = len(df)
            results[col] = (success_count / total_count * 100) if total_count > 0 else 0.0
        except Exception as e:
            logger.warning(f"Failed to validate amounts in {col}: {e}")
            results[col] = 0.0

    return results


def map_emma_resource(df: pd.DataFrame, resource_type: str) -> tuple:
    """Map EMMA DataFrame to standard normalized format with validation.

    Args:
        df: Input DataFrame from EMMA download
        resource_type: 'bonds' or 'underwriters'

    Returns:
        (normalized_df: pd.DataFrame, validation_report: dict)
    """
    if resource_type not in EMMA_MAPPINGS:
        logger.error(f"Unknown EMMA resource type: {resource_type}")
        return df, {"error": f"Unknown resource type: {resource_type}"}

    config = EMMA_MAPPINGS[resource_type]

    # Validate dates and amounts
    date_validation = validate_dates(df, list(config["date_cols"]))
    amount_validation = validate_amounts(df, list(config["amount_cols"]))

    # Check for threshold violations (>5% unparsed = warning)
    threshold = 95.0
    failed_dates = {k: v for k, v in date_validation.items() if v < threshold}
    failed_amounts = {k: v for k, v in amount_validation.items() if v < threshold}

    report = {
        "resource_type": resource_type,
        "rows": len(df),
        "date_validation": date_validation,
        "amount_validation": amount_validation,
        "failed_dates": failed_dates,
        "failed_amounts": failed_amounts,
        "threshold_met": len(failed_dates) == 0 and len(failed_amounts) == 0,
    }

    # Log validation results
    if report["threshold_met"]:
        logger.info(f"✓ {resource_type} validation passed: all dates/amounts >95%")
    else:
        if failed_dates:
            logger.warning(f"⚠ {resource_type} date parsing issues: {failed_dates}")
        if failed_amounts:
            logger.warning(f"⚠ {resource_type} amount parsing issues: {failed_amounts}")

    # Return normalized DataFrame (currently as-is; can add column renaming if needed)
    return df, report


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    # Example usage
    sample_bonds = pd.DataFrame(
        {
            "cusip": ["PR123456", "PR234567"],
            "isin": ["USP12345678", "USP23456789"],
            "issuer_name": ["Puerto Rico Electric", "Puerto Rico Water Authority"],
            "issue_date": ["2015-06-15", "2016-03-10"],
            "maturity_date": ["2045-06-15", "2050-03-10"],
            "par_amount": [100000000, 75000000],
        }
    )

    df_norm, report = map_emma_resource(sample_bonds, "bonds")
    print(f"Report: {report}")
