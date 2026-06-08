"""Deterministic column mapping for FDIC bank institution data.

Maps FDIC institution and financial columns to standard normalized format
with validation of date/amount parsing.
"""

import pandas as pd
import logging

logger = logging.getLogger(__name__)

# Deterministic mappings for FDIC data
FDIC_MAPPINGS = {
    "institutions": {
        "description": "FDIC-insured bank institution profiles",
        "date_cols": ["established_date", "end_date", "latest_report_date"],
        "amount_cols": ["total_assets", "total_deposits", "net_loans", "securities", "net_income"],
        "id_cols": ["cert"],
        "entity_col": "name",
    },
    "financials": {
        "description": "FDIC bank call report financial history",
        "date_cols": ["report_date"],
        "amount_cols": [
            "total_assets",
            "total_deposits",
            "net_loans",
            "securities",
            "net_income",
            "interest_income",
            "noninterest_income",
            "noninterest_expense",
            "loan_loss_provision",
            "net_chargeoffs",
            "total_equity",
            "total_liabilities",
        ],
        "id_cols": ["cert"],
        "year_col": "report_year",
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


def map_fdic_resource(df: pd.DataFrame, resource_type: str) -> tuple:
    """Map FDIC DataFrame to standard normalized format with validation.

    Args:
        df: Input DataFrame from FDIC download
        resource_type: 'institutions' or 'financials'

    Returns:
        (normalized_df: pd.DataFrame, validation_report: dict)
    """
    if resource_type not in FDIC_MAPPINGS:
        logger.error(f"Unknown FDIC resource type: {resource_type}")
        return df, {"error": f"Unknown resource type: {resource_type}"}

    config = FDIC_MAPPINGS[resource_type]

    # Validate dates and amounts
    date_validation = validate_dates(df, config["date_cols"])
    amount_validation = validate_amounts(df, config["amount_cols"])

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
    sample_inst = pd.DataFrame(
        {
            "cert": [123, 456],
            "name": ["Bank A", "Bank B"],
            "established_date": ["2000-01-15", "1995-06-20"],
            "total_assets": [100000000, 250000000],
        }
    )

    df_norm, report = map_fdic_resource(sample_inst, "institutions")
    print(f"Report: {report}")
