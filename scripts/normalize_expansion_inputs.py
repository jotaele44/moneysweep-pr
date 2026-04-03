"""
Normalize expansion CSV inputs (Section 7).
Reads CSVs from data/staging/expansion/, maps columns to standard names,
standardizes dates, derives fiscal year, deduplicates, and outputs to
data/staging/processed/normalized_expansion_*.csv.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from scripts.config import (
    DOWNLOAD_MANIFEST,
    EXPANSION_DIR,
    PROCESSED_DIR,
    PROJECT_ROOT,
    STANDARD_COLUMNS,
    find_column,
    get_normalized_filename,
    read_csv_safe,
    setup_logging,
)


def build_column_map(df_columns: list) -> dict:
    """
    Build a mapping from standard column names to actual column names in the CSV.
    Returns: {standard_name: actual_col_name_or_None}
    """
    families = ["contract_id", "date", "vendor", "agency", "amount", "pop_state"]
    standard_names = ["contract_id", "award_date", "vendor_name", "agency_name", "obligated_amount", "pop_state"]

    col_map = {}
    for family, std_name in zip(families, standard_names):
        col_map[std_name] = find_column(df_columns, family)

    return col_map


def derive_fiscal_year(date_series: pd.Series) -> pd.Series:
    """
    Derive federal fiscal year from a datetime Series.
    Fiscal year: if month >= 10, year + 1; else year.
    NaT values produce NaN.
    """
    fy = pd.Series(pd.NA, index=date_series.index, dtype="Int64")
    mask = date_series.notna()
    if mask.any():
        months = date_series[mask].dt.month
        years = date_series[mask].dt.year
        fy[mask] = years.where(months < 10, years + 1)
    return fy


def normalize_file(input_path: Path, output_dir: Path, logger) -> dict:
    """
    Normalize a single expansion CSV. Returns a result dict.
    """
    result = {
        "filename": input_path.name,
        "input_rows": 0,
        "output_rows": 0,
        "date_parsed_pct": 0.0,
        "fiscal_years": set(),
        "status": "OK",
        "output_path": None,
        "errors": [],
    }

    # Read CSV
    try:
        df = read_csv_safe(input_path)
    except Exception as e:
        result["status"] = "ERROR"
        result["errors"].append(f"Failed to read: {e}")
        logger.error(f"  {input_path.name}: Failed to read - {e}")
        return result

    result["input_rows"] = len(df)

    if len(df) == 0:
        result["status"] = "WARN"
        result["errors"].append("Empty file")
        logger.warning(f"  {input_path.name}: Empty file (0 rows)")
        # Still write output (empty CSV with headers)

    # Build column map
    col_map = build_column_map(df.columns.tolist())
    logger.debug(f"  {input_path.name}: Column map: {col_map}")

    # Rename matched columns to standard names
    rename_map = {}
    for std_name, actual_col in col_map.items():
        if actual_col is not None and actual_col in df.columns:
            # Only rename if different
            if actual_col != std_name:
                rename_map[actual_col] = std_name

    df = df.rename(columns=rename_map)

    # Ensure all standard columns exist (fill missing with NaN)
    for std_col in STANDARD_COLUMNS:
        if std_col not in df.columns:
            df[std_col] = pd.NA

    # Parse dates
    if col_map["award_date"] is not None or "award_date" in df.columns:
        try:
            df["award_date"] = pd.to_datetime(
                df["award_date"], format="mixed", dayfirst=False, errors="coerce"
            )
            if len(df) > 0:
                parsed_count = df["award_date"].notna().sum()
                result["date_parsed_pct"] = round(parsed_count / len(df) * 100, 1)
        except Exception as e:
            logger.warning(f"  {input_path.name}: Date parsing issue - {e}")
            df["award_date"] = pd.NaT
    else:
        df["award_date"] = pd.NaT

    # Convert amount to numeric
    if "obligated_amount" in df.columns:
        raw_amounts = df["obligated_amount"].astype(str).str.replace(",", "").str.replace("$", "").str.strip()
        df["obligated_amount"] = pd.to_numeric(raw_amounts, errors="coerce")
        coerced = raw_amounts.notna().sum() - df["obligated_amount"].notna().sum()
        if coerced > 0:
            logger.warning(f"  {input_path.name}: {coerced} non-numeric amount values coerced to NaN")

    # Derive fiscal year
    df["fiscal_year"] = derive_fiscal_year(df["award_date"])

    # Add source file tag
    df["source_file"] = input_path.stem

    # Deduplicate (within file only)
    before_dedup = len(df)
    df = df.drop_duplicates()
    if before_dedup > len(df):
        logger.info(f"  {input_path.name}: Removed {before_dedup - len(df)} duplicate rows")

    result["output_rows"] = len(df)

    # Collect fiscal years found
    if "fiscal_year" in df.columns:
        fy_values = df["fiscal_year"].dropna().unique()
        result["fiscal_years"] = set(int(y) for y in fy_values)

    # Write output
    output_name = get_normalized_filename(input_path.name)
    output_path = output_dir / output_name
    output_dir.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_path, index=False, encoding="utf-8")
    result["output_path"] = output_path

    logger.info(
        f"  {input_path.name} -> {output_name}: "
        f"{result['input_rows']} rows in, {result['output_rows']} rows out, "
        f"{result['date_parsed_pct']}% dates parsed, "
        f"FY range: {min(result['fiscal_years']) if result['fiscal_years'] else 'N/A'}-"
        f"{max(result['fiscal_years']) if result['fiscal_years'] else 'N/A'}"
    )

    return result


def normalize_all(root: Path = None) -> list:
    """Normalize all expansion CSVs. Returns list of result dicts."""
    if root is None:
        root = PROJECT_ROOT

    expansion_dir = root / "data" / "staging" / "expansion"
    processed_dir = root / "data" / "staging" / "processed"
    logger = setup_logging("normalization_report")

    results = []
    expected_files = [m["filename"] for m in DOWNLOAD_MANIFEST]

    for fname in expected_files:
        input_path = expansion_dir / fname
        if not input_path.exists():
            logger.debug(f"  Skipping {fname}: file not found")
            continue
        result = normalize_file(input_path, processed_dir, logger)
        results.append(result)

    return results


def print_report(results: list, logger) -> None:
    """Print normalization report."""
    logger.info("")
    logger.info("=" * 70)
    logger.info("NORMALIZATION REPORT")
    logger.info("=" * 70)

    if not results:
        logger.info("No files to normalize. Download expansion CSVs first.")
        return

    header = f"{'Filename':<50} {'In':>8} {'Out':>8} {'Date%':>7} {'FY Range':>12} {'Status':>6}"
    logger.info(header)
    logger.info("-" * len(header))

    for r in results:
        fy_range = "N/A"
        if r["fiscal_years"]:
            fy_range = f"{min(r['fiscal_years'])}-{max(r['fiscal_years'])}"
        row = (
            f"{r['filename']:<50} "
            f"{r['input_rows']:>8} "
            f"{r['output_rows']:>8} "
            f"{r['date_parsed_pct']:>6.1f}% "
            f"{fy_range:>12} "
            f"{r['status']:>6}"
        )
        logger.info(row)

    total_in = sum(r["input_rows"] for r in results)
    total_out = sum(r["output_rows"] for r in results)
    all_fy = set()
    for r in results:
        all_fy.update(r["fiscal_years"])

    logger.info("-" * 90)
    logger.info(f"Total: {len(results)} files, {total_in} input rows, {total_out} output rows")
    if all_fy:
        logger.info(f"Fiscal years found: {sorted(all_fy)}")
    logger.info("")


def main(root: Path = None) -> int:
    """Run normalization. Returns count of successfully normalized files."""
    if root is None:
        root = PROJECT_ROOT

    logger = setup_logging("normalization_report")
    logger.info("Normalizing expansion inputs...")

    results = normalize_all(root)
    print_report(results, logger)

    ok_count = sum(1 for r in results if r["status"] in ("OK", "WARN"))
    err_count = sum(1 for r in results if r["status"] == "ERROR")

    if err_count > 0:
        logger.warning(f"{err_count} file(s) had errors during normalization.")

    logger.info(f"Normalized {ok_count} of {len(DOWNLOAD_MANIFEST)} expected files.")
    return ok_count


if __name__ == "__main__":
    count = main()
    print(f"\nNormalized {count} files.")
    sys.exit(0 if count > 0 else 1)
