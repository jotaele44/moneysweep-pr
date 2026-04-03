"""
Validate downloaded expansion CSV files (Section 6).
Checks: file exists, non-empty, has required column families, non-null data.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.config import (
    DOWNLOAD_MANIFEST,
    EXPANSION_DIR,
    LOGS_DIR,
    PROJECT_ROOT,
    find_column,
    read_csv_safe,
    setup_logging,
)


def validate_file(filepath: Path, logger) -> dict:
    """
    Validate a single CSV file. Returns a result dict with:
    - filename, exists, rows, date_col, vendor_col, agency_col, amount_col,
      has_data (at least one row with non-null vendor+agency+amount), status
    """
    result = {
        "filename": filepath.name,
        "exists": False,
        "rows": 0,
        "date_col": None,
        "vendor_col": None,
        "agency_col": None,
        "amount_col": None,
        "has_data": False,
        "status": "FAIL",
        "errors": [],
        "warnings": [],
    }

    # Check existence
    if not filepath.exists():
        result["errors"].append("File not found")
        return result

    result["exists"] = True

    # Try to read the CSV
    try:
        df = read_csv_safe(filepath)
    except Exception as e:
        result["errors"].append(f"CSV parse error: {e}")
        return result

    # Row count
    result["rows"] = len(df)
    if len(df) == 0:
        result["errors"].append("File is empty (0 rows)")
        return result

    # Column matching
    result["date_col"] = find_column(df.columns.tolist(), "date")
    result["vendor_col"] = find_column(df.columns.tolist(), "vendor")
    result["agency_col"] = find_column(df.columns.tolist(), "agency")
    result["amount_col"] = find_column(df.columns.tolist(), "amount")

    if result["date_col"] is None:
        result["warnings"].append("No date column found (award_date)")
    if result["vendor_col"] is None:
        result["warnings"].append("No vendor/recipient column found")
    if result["agency_col"] is None:
        result["warnings"].append("No agency column found")
    if result["amount_col"] is None:
        result["warnings"].append("No amount column found")

    # Check at least one row has non-null values in key fields
    data_cols = [
        c for c in [result["vendor_col"], result["agency_col"], result["amount_col"]]
        if c is not None
    ]
    if data_cols:
        has_any = False
        for col in data_cols:
            if df[col].notna().any() and (df[col].astype(str).str.strip() != "").any():
                has_any = True
                break
        result["has_data"] = has_any
        if not has_any:
            result["warnings"].append("All key data columns are empty/null")
    else:
        result["warnings"].append("Cannot check data: no key columns matched")

    # Row count sanity
    if result["rows"] < 50:
        result["warnings"].append(f"Suspiciously low row count: {result['rows']}")

    # Determine status
    if result["errors"]:
        result["status"] = "FAIL"
    elif result["warnings"]:
        result["status"] = "WARN"
    else:
        result["status"] = "PASS"

    return result


def validate_all(root: Path = None) -> list:
    """Validate all expected expansion files. Returns list of result dicts."""
    if root is None:
        root = PROJECT_ROOT

    logger = setup_logging("validation_report")
    expansion_dir = root / "data" / "staging" / "expansion"
    results = []

    for entry in DOWNLOAD_MANIFEST:
        filepath = expansion_dir / entry["filename"]
        logger.debug(f"Validating: {entry['filename']}")
        result = validate_file(filepath, logger)
        results.append(result)

        if result["errors"]:
            for err in result["errors"]:
                logger.warning(f"  {entry['filename']}: {err}")
        if result["warnings"]:
            for warn in result["warnings"]:
                logger.info(f"  {entry['filename']}: {warn}")

    return results


def print_report(results: list, logger) -> None:
    """Print a formatted validation report."""
    # Header
    header = f"{'Filename':<50} {'Exists':>6} {'Rows':>8} {'Date':>6} {'Vendor':>8} {'Agency':>8} {'Amount':>8} {'Status':>6}"
    sep = "-" * len(header)

    logger.info("")
    logger.info("=" * 70)
    logger.info("DOWNLOAD VALIDATION REPORT")
    logger.info("=" * 70)
    logger.info(header)
    logger.info(sep)

    for r in results:
        row = (
            f"{r['filename']:<50} "
            f"{'Y' if r['exists'] else 'N':>6} "
            f"{r['rows']:>8} "
            f"{'Y' if r['date_col'] else 'N':>6} "
            f"{'Y' if r['vendor_col'] else 'N':>8} "
            f"{'Y' if r['agency_col'] else 'N':>8} "
            f"{'Y' if r['amount_col'] else 'N':>8} "
            f"{r['status']:>6}"
        )
        logger.info(row)

    logger.info(sep)

    # Summary
    total = len(results)
    passed = sum(1 for r in results if r["status"] == "PASS")
    warned = sum(1 for r in results if r["status"] == "WARN")
    failed = sum(1 for r in results if r["status"] == "FAIL")
    logger.info(f"Total: {total} | Passed: {passed} | Warnings: {warned} | Failed: {failed}")
    logger.info("")

    # Failure details
    if failed > 0:
        missing = [r["filename"] for r in results if not r["exists"]]
        if missing:
            logger.info("Missing files:")
            for f in missing:
                logger.info(f"  - {f}")
            logger.info("")
            logger.info(
                "Please follow the instructions in data/staging/expansion/DOWNLOAD_INSTRUCTIONS.md"
            )
            logger.info("Then re-run: python3 scripts/validate_downloads.py")


def main(root: Path = None) -> int:
    """
    Run download validation. Returns:
    0 = all pass, 1 = any fail, 2 = warnings only
    """
    if root is None:
        root = PROJECT_ROOT

    logger = setup_logging("validation_report")
    results = validate_all(root)
    print_report(results, logger)

    # Also write to log file
    log_path = root / "data" / "logs" / "validation_report.log"
    logger.info(f"Report written to: {log_path.relative_to(root)}")

    has_fail = any(r["status"] == "FAIL" for r in results)
    has_warn = any(r["status"] == "WARN" for r in results)

    if has_fail:
        return 1
    elif has_warn:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
