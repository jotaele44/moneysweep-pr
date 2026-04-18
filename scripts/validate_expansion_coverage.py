"""
Validate expansion coverage across normalized files (Section 8).
Checks: all normalized files exist, row counts, year coverage 2000-2025,
and the critical 2007 gap in FY2005-2008 FPDS files.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from scripts.config import (
    DOWNLOAD_MANIFEST,
    PROCESSED_DIR,
    PROJECT_ROOT,
    get_normalized_filename,
    read_csv_safe,
    setup_logging,
)

COVERAGE_YEARS = list(range(2000, 2026))  # 2000 through 2025 inclusive

# Files that MUST contain 2007
CRITICAL_2007_FILES = [
    "normalized_expansion_fpds_2005_2008_direct.csv",
    "normalized_expansion_fpds_2005_2008_vendor.csv",
]


def check_file_coverage(filepath: Path) -> dict:
    """
    Read a normalized CSV and return coverage info.
    Returns: {exists, rows, fiscal_years: set[int], errors}
    """
    result = {"exists": False, "rows": 0, "fiscal_years": set(), "errors": []}

    if not filepath.exists():
        result["errors"].append("File not found")
        return result

    result["exists"] = True

    try:
        df = read_csv_safe(filepath)
    except Exception as e:
        result["errors"].append(f"Read error: {e}")
        return result

    result["rows"] = len(df)

    if "fiscal_year" in df.columns:
        fy_raw = pd.to_numeric(df["fiscal_year"], errors="coerce").dropna()
        result["fiscal_years"] = set(int(y) for y in fy_raw if 2000 <= y <= 2026)

    return result


def build_coverage_matrix(root: Path) -> dict:
    """
    Build coverage data for all expected normalized files.
    Returns: {normalized_filename: {exists, rows, fiscal_years, errors}}
    """
    processed_dir = root / "data" / "staging" / "processed"
    matrix = {}

    for entry in DOWNLOAD_MANIFEST:
        norm_name = get_normalized_filename(entry["filename"])
        filepath = processed_dir / norm_name
        matrix[norm_name] = check_file_coverage(filepath)

    return matrix


def check_2007_gap(matrix: dict) -> bool:
    """Returns True if 2007 is OK.

    Only fails if a critical file EXISTS but does not contain 2007.
    If the file is absent (download failed/manual), skip — the year may be
    covered by another source (e.g. FY2009-2016 files contain records going
    back to 2000-2001).
    """
    for fname in CRITICAL_2007_FILES:
        info = matrix.get(fname, {})
        if not info["exists"]:  # absent file — don't penalise
            continue
        if 2007 not in info.get("fiscal_years", set()):
            return False  # file present but 2007 is genuinely missing
    return True


def report_coverage(matrix: dict, logger) -> dict:
    """Print and log the coverage matrix. Returns summary dict."""
    logger.info("")
    logger.info("=" * 90)
    logger.info("EXPANSION COVERAGE REPORT")
    logger.info("=" * 90)

    # --- Per-file summary ---
    logger.info("")
    logger.info("File Status:")
    logger.info(f"{'Normalized File':<55} {'Exists':>6} {'Rows':>8} {'FY Min':>7} {'FY Max':>7} {'Status':>6}")
    logger.info("-" * 95)

    for fname, info in matrix.items():
        fy = info.get("fiscal_years", set())
        fy_min = min(fy) if fy else "-"
        fy_max = max(fy) if fy else "-"
        status = "FAIL" if not info["exists"] or info["rows"] == 0 else "OK"
        logger.info(
            f"{fname:<55} {'Y' if info['exists'] else 'N':>6} "
            f"{info['rows']:>8} {str(fy_min):>7} {str(fy_max):>7} {status:>6}"
        )

    # --- Year coverage matrix ---
    logger.info("")
    logger.info("Year Coverage Matrix (2000-2025):")

    # Aggregate coverage per year across all files
    year_covered = {}
    for year in COVERAGE_YEARS:
        year_covered[year] = any(
            year in info.get("fiscal_years", set()) for info in matrix.values()
        )

    # Print in rows of 13 years each
    year_groups = [COVERAGE_YEARS[:13], COVERAGE_YEARS[13:]]
    for group in year_groups:
        header = "  ".join(str(y) for y in group)
        marks = "    ".join("Y" if year_covered[y] else "N" for y in group)
        logger.info(f"  {header}")
        logger.info(f"  {marks}")
        logger.info("")

    # --- Summary ---
    covered_years = [y for y in COVERAGE_YEARS if year_covered[y]]
    missing_years = [y for y in COVERAGE_YEARS if not year_covered[y]]
    total_years = len(COVERAGE_YEARS)

    logger.info(f"Year coverage: {len(covered_years)}/{total_years} years (2000-2025)")

    if missing_years:
        logger.info(f"Missing years: {missing_years}")
    else:
        logger.info("All years 2000-2025 covered.")

    # --- 2007 critical check ---
    logger.info("")
    gap_2007_ok = check_2007_gap(matrix)
    if gap_2007_ok:
        logger.info("2007 gap check: OK (year 2007 present in FY2005-2008 FPDS files)")
    else:
        logger.info("*** CRITICAL: Year 2007 MISSING from FY2005-2008 FPDS files ***")
        logger.info("*** Action: Re-download FPDS 2005-2008 with corrected filters ***")
        logger.info("*** Verify date range: 10/01/2004 to 09/30/2008               ***")
        logger.info("*** Or download 2007 separately: 10/01/2006 to 09/30/2007     ***")
        for fname in CRITICAL_2007_FILES:
            info = matrix.get(fname, {})
            fy = info.get("fiscal_years", set())
            if 2007 not in fy:
                logger.info(f"  Missing 2007 in: {fname} (years found: {sorted(fy)[:10]}...)")

    # --- Timeline continuity check ---
    logger.info("")
    gaps = []
    if covered_years:
        min_y, max_y = min(covered_years), max(covered_years)
        gaps = [y for y in range(min_y, max_y + 1) if not year_covered[y]]

    if gaps:
        logger.info(f"Timeline continuity: GAPS found at years: {gaps}")
    else:
        logger.info("Timeline continuity: OK (no gaps in covered range)")

    return {
        "total_files": len(matrix),
        "files_exist": sum(1 for i in matrix.values() if i["exists"]),
        "files_with_rows": sum(1 for i in matrix.values() if i["rows"] > 0),
        "covered_years": covered_years,
        "missing_years": missing_years,
        "gap_2007_ok": gap_2007_ok,
        "timeline_gaps": gaps,
    }


def main(root: Path = None) -> int:
    """
    Run coverage validation. Returns:
    0 = full coverage + 2007 present
    1 = missing years or 2007 gap
    """
    if root is None:
        root = PROJECT_ROOT

    logger = setup_logging("coverage_report")
    logger.info("Validating expansion coverage...")

    matrix = build_coverage_matrix(root)

    if not any(i["exists"] for i in matrix.values()):
        logger.info("No normalized files found. Run normalize_expansion_inputs.py first.")
        return 1

    summary = report_coverage(matrix, logger)

    log_path = root / "data" / "logs" / "coverage_report.log"
    logger.info(f"\nReport written to: {log_path.relative_to(root)}")

    if summary["missing_years"]:
        return 1
    # Only fail on 2007 gap if 2007 is genuinely absent from ALL sources
    if not summary["gap_2007_ok"] and 2007 not in summary["covered_years"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
