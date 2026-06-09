"""Deterministic column mapping for CMS (Centers for Medicare & Medicaid Services) data.

Maps CMS Open Payments and Medicare provider columns to standard normalized format
with validation of date/amount parsing.
"""

import pandas as pd
import logging

logger = logging.getLogger(__name__)

# Deterministic mappings for CMS data
CMS_MAPPINGS = {
    "open_payments": {
        "description": "CMS Open Payments (Sunshine Act) — pharma/device payments to providers",
        "date_cols": ["payment_year"],
        "amount_cols": ["total_amount"],
        "id_cols": ["covered_recipient_npi"],
        "entity_col": "recipient_name",
        "location_cols": ["recipient_city", "recipient_state"],
    },
    "medicare": {
        "description": "Medicare Part B provider reimbursements and service metrics",
        "date_cols": [],
        "amount_cols": [
            "total_submitted_charges",
            "total_medicare_allowed",
            "total_medicare_payment",
            "total_medicare_standardized",
        ],
        "id_cols": ["npi"],
        "entity_col": "provider_name",
        "location_cols": ["provider_city", "provider_state"],
        "service_cols": ["total_services", "total_unique_benes"],
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
            logger.warning(f"Date validation error for {col}: {e}")
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
            logger.warning(f"Amount validation error for {col}: {e}")
            results[col] = 0.0

    return results


def map_cms_resource(df: pd.DataFrame, resource_type: str, threshold: float = 95.0) -> tuple:
    """Normalize CMS data to standard format with validation gates.

    Args:
        df: Raw CMS DataFrame
        resource_type: "open_payments" or "medicare"
        threshold: Minimum % success for dates/amounts (default 95%)

    Returns:
        (normalized_df, validation_report) where validation_report contains:
            - date_validation: {col: success_pct}
            - amount_validation: {col: success_pct}
            - threshold_met: bool (all validated cols >= threshold)
            - issues: list of columns below threshold
    """
    if resource_type not in CMS_MAPPINGS:
        raise ValueError(f"Unknown CMS resource type: {resource_type}")

    mapping = CMS_MAPPINGS[resource_type]
    report = {
        "resource_type": resource_type,
        "row_count": len(df),
        "column_count": len(df.columns),
        "date_validation": {},
        "amount_validation": {},
        "threshold_met": True,
        "issues": [],
    }

    # Validate dates
    date_results = validate_dates(df, list(mapping["date_cols"]))
    report["date_validation"] = date_results

    # Validate amounts
    amount_results = validate_amounts(df, list(mapping["amount_cols"]))
    report["amount_validation"] = amount_results

    # Check threshold
    all_results = {**date_results, **amount_results}
    below_threshold = [col for col, pct in all_results.items() if pct < threshold]

    if below_threshold:
        report["threshold_met"] = False
        report["issues"] = below_threshold
        logger.warning(
            f"CMS {resource_type}: {len(below_threshold)} columns below {threshold}% threshold: "
            f"{below_threshold}"
        )

    # Return normalized df (passthrough for now; minimal transformation needed)
    return df, report


if __name__ == "__main__":
    # Quick validation example
    test_df_open = pd.DataFrame(
        {
            "payment_year": [2022, 2023, 2023],
            "covered_recipient_npi": [1111111111, 2222222222, 3333333333],
            "recipient_name": ["Dr. Smith", "Dr. Jones", "Hospital A"],
            "total_amount": [1000.50, 2500.75, 5000.00],
        }
    )

    df_norm, report = map_cms_resource(test_df_open, "open_payments")
    print(f"Open Payments validation: {report}")

    test_df_medicare = pd.DataFrame(
        {
            "npi": [1111111111, 2222222222],
            "provider_name": ["Dr. Smith", "Dr. Jones"],
            "total_submitted_charges": [100000, 250000],
            "total_medicare_payment": [85000, 210000],
            "total_services": [500, 1200],
        }
    )

    df_norm, report = map_cms_resource(test_df_medicare, "medicare")
    print(f"Medicare validation: {report}")
