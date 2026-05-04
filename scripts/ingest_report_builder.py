"""
Ingest FPDS / USASpending Report Builder Excel exports for Puerto Rico.

These are annual procurement data files manually downloaded from FPDS.gov
Report Builder or USASpending.gov Advanced Search, covering FY2018–FY2024.

Expected files in data/raw/ (any order):
  Report Builder FY20 Revised.xlsx
  Report Builder FY21 Revised.xlsx
  Report Builder FY22  Revised.xlsx
  Report Builder FY23 Revised.xlsx
  Report Builder FY24 Final rev2.xlsx
  FY_2018_Federal_Procurement_with_Subk_Plan_.xls
  FY_2019_Federal_Procurement_with_Subk_Plan_.xlsx

Output:
  data/staging/processed/pr_report_builder_master.csv

Usage:
  python3 scripts/ingest_report_builder.py
  python3 scripts/ingest_report_builder.py --force
"""

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from scripts.config import PROJECT_ROOT, setup_logging

# Canonical output schema (matches build_unified_master.py CANONICAL_COLUMNS)
MASTER_COLUMNS = [
    "award_id", "recipient_name", "recipient_name_normalized",
    "recipient_uei", "awarding_agency", "awarding_sub_agency",
    "obligated_amount", "award_date", "fiscal_year",
    "pop_state", "pop_county", "description",
    "source_file", "source_dataset", "award_category",
    "naics_code", "psc_code",
]

# Flexible column mapping: output_col → [candidate input column names]
COL_MAP = {
    "recipient_name": [
        "Vendor Name", "Recipient Name", "Awardee/Recipient Name",
        "Contractor Name", "Legal Business Name", "vendorname",
        "Awardee Name", "Company Name",
    ],
    "recipient_uei": [
        "Unique Entity ID (SAM)", "UEI", "Unique Entity Identifier",
        "DUNS Number", "Vendor DUNS Number", "DUNS",
    ],
    "award_id": [
        "Award ID", "PIID", "Contract Number", "Award/Procurement ID",
        "Procurement Instrument Identifier", "Transaction Number",
    ],
    "obligated_amount": [
        "Action Obligation", "Obligated Amount", "Total Obligated Amount",
        "Base and All Options Value (Total Contract Value)", "Dollars Obligated",
        "Obligated Amount ($ Dollars)", "Total Obligated",
    ],
    "award_date": [
        "Award Date", "Action Date", "Date Signed", "Effective Date",
        "Date of Award", "Contract Award Date",
    ],
    "awarding_agency": [
        "Awarding Agency Name", "Contracting Agency Name", "Department Name",
        "Funding Agency Name", "Department/Ind. Agency",
    ],
    "awarding_sub_agency": [
        "Awarding Sub Agency Name", "Contracting Office Name",
        "Sub Agency Name", "Contracting Agency Name", "CGAC Agency Code",
    ],
    "pop_state": [
        "Place of Performance State Code", "Place of Performance State",
        "Primary Place of Performance State Code",
        "Principal Place of Performance State Code",
        "Pop State Code", "Performance State",
    ],
    "pop_county": [
        "Place of Performance County Name", "Place of Performance City",
        "Primary Place of Performance County Name",
        "Pop County Name",
    ],
    "description": [
        "Award Description", "Description of Requirement",
        "Purpose of Modification", "Award/Contract Description",
        "Description", "Project Description",
    ],
    "award_category": [
        "Award Type", "Type of Contract Pricing", "Award/IDV Type",
        "Contract Award Type", "Type",
    ],
    "fiscal_year": [
        "Fiscal Year", "FY of Action", "Action Fiscal Year",
        "Fiscal Year (FY)", "FY",
    ],
    "naics_code": [
        "NAICS Code", "NAICS", "NAICS Description",
        "Industry Code (NAICS)",
    ],
    "psc_code": [
        "Product or Service Code", "PSC Code", "PSC",
        "Product/Service Code",
    ],
}

# PR state identifiers (various forms seen in FPDS exports)
PR_STATE_VALUES = {"PR", "72", "PUERTO RICO", "Puerto Rico"}

_STRIP_RE = re.compile(r"[^\w\s]")
_SPACE_RE = re.compile(r"\s+")
_NAME_SUFFIXES = {
    "INC", "LLC", "CORP", "LTD", "CO", "LP", "LLP",
    "COMPANY", "CORPORATION", "INCORPORATED", "LIMITED",
}


def _normalize_name(name):
    if not name or pd.isna(name):
        return ""
    n = str(name).upper()
    n = _STRIP_RE.sub(" ", n)
    n = _SPACE_RE.sub(" ", n).strip()
    tokens = n.split()
    while tokens and tokens[-1] in _NAME_SUFFIXES:
        tokens.pop()
    return " ".join(tokens)


def _map_col(df_cols, candidates):
    """Return first candidate column name that exists in df_cols (case-insensitive)."""
    cols_lower = {c.lower(): c for c in df_cols}
    for cand in candidates:
        if cand in df_cols:
            return cand
        if cand.lower() in cols_lower:
            return cols_lower[cand.lower()]
    return None


def _derive_fy_from_filename(path):
    """Extract fiscal year from filename: 'FY20', 'FY2020', 'FY_2018', etc."""
    name = path.stem
    m = re.search(r"FY[_\s]?(\d{2,4})", name, re.I)
    if not m:
        return ""
    yr = m.group(1)
    if len(yr) == 2:
        yr = "20" + yr
    return yr


def _read_excel_file(path, logger):
    """Read an Excel file (.xls or .xlsx), try each sheet, return largest DataFrame."""
    try:
        xl = pd.ExcelFile(path)
        best = pd.DataFrame()
        for sheet in xl.sheet_names:
            try:
                df = pd.read_excel(xl, sheet_name=sheet, dtype=str, na_filter=False)
                if len(df) > len(best):
                    best = df
            except Exception as e:
                logger.debug(f"    Sheet {sheet!r} failed: {e}")
        if best.empty:
            logger.warning(f"  No data found in {path.name}")
        else:
            logger.info(f"  Read {len(best):,} rows from {path.name} (sheet count: {len(xl.sheet_names)})")
        return best
    except Exception as e:
        logger.warning(f"  Failed to read {path.name}: {e}")
        return pd.DataFrame()


def _parse_file(path, logger):
    """Parse one Report Builder file into canonical master rows."""
    suffix = path.suffix.lower()
    if suffix in (".xlsx", ".xls"):
        df = _read_excel_file(path, logger)
    elif suffix == ".csv":
        try:
            df = pd.read_csv(path, dtype=str, na_filter=False, encoding="utf-8", low_memory=False)
            logger.info(f"  Read {len(df):,} rows from {path.name}")
        except Exception:
            try:
                df = pd.read_csv(path, dtype=str, na_filter=False, encoding="latin-1", low_memory=False)
                logger.info(f"  Read {len(df):,} rows from {path.name} (latin-1)")
            except Exception as e:
                logger.warning(f"  Failed to read {path.name}: {e}")
                return pd.DataFrame()
    else:
        logger.warning(f"  Unsupported file type: {path.name}")
        return pd.DataFrame()

    if df.empty:
        return pd.DataFrame()

    # Build output row by row using flexible column mapping
    out = {}
    for out_col, candidates in COL_MAP.items():
        src = _map_col(df.columns.tolist(), candidates)
        out[out_col] = df[src] if src else ""

    result = pd.DataFrame(out)

    # Derive fiscal year from filename if not in data
    filename_fy = _derive_fy_from_filename(path)
    if "fiscal_year" not in result.columns or result["fiscal_year"].eq("").all():
        result["fiscal_year"] = filename_fy
    else:
        mask = result["fiscal_year"].astype(str).str.strip().eq("")
        result.loc[mask, "fiscal_year"] = filename_fy

    result["source_file"] = path.name
    result["source_dataset"] = "report_builder"

    # Filter for PR records
    pop_col = _map_col(df.columns.tolist(), COL_MAP["pop_state"])
    if pop_col:
        pop_vals = df[pop_col].astype(str).str.strip().str.upper()
        pr_mask = pop_vals.isin({v.upper() for v in PR_STATE_VALUES})
        # Also check recipient state columns if pop_state doesn't yield PR records
        if pr_mask.sum() == 0:
            logger.info(f"  No PR rows from pop_state; trying recipient state cols...")
            for cand in ["Vendor State Code", "Recipient State Code", "State Code",
                         "Legal Business Name State", "Vendor State"]:
                src2 = _map_col(df.columns.tolist(), [cand])
                if src2:
                    mask2 = df[src2].astype(str).str.strip().str.upper().isin(
                        {v.upper() for v in PR_STATE_VALUES}
                    )
                    pr_mask = pr_mask | mask2
        result = result[pr_mask.values].copy()
    else:
        logger.info(f"  No pop_state column found; keeping all {len(result):,} rows")

    # Normalize recipient name
    result["recipient_name_normalized"] = result["recipient_name"].apply(_normalize_name)

    logger.info(f"  → {len(result):,} PR rows from {path.name}")
    return result


def _find_report_builder_files(raw_dir, logger):
    """Locate all Report Builder Excel files in data/raw/."""
    patterns = [
        "Report Builder*.xlsx",
        "Report Builder*.xls",
        "report builder*.xlsx",
        "FY_201*.xls",
        "FY_201*.xlsx",
        "FY_202*.xlsx",
        "*Federal*Procurement*.xlsx",
        "*Federal*Procurement*.xls",
    ]
    found = set()
    for pattern in patterns:
        for f in raw_dir.glob(pattern):
            found.add(f)
    if not found:
        # Also search one level deep in subdirs
        for pattern in patterns:
            for f in raw_dir.glob(f"*/{pattern}"):
                found.add(f)
    files = sorted(found)
    logger.info(f"  Found {len(files)} Report Builder files")
    for f in files:
        logger.info(f"    {f.name}")
    return files


def _file_has_data(path):
    if not path.exists():
        return False
    try:
        return len(pd.read_csv(path, dtype=str, nrows=2)) > 0
    except Exception:
        return False


def run(root=None):
    return _run(root=root, force=False)


def _run(root=None, force=False):
    if root is None:
        root = PROJECT_ROOT
    out_path = root / "data" / "staging" / "processed" / "pr_report_builder_master.csv"
    raw_dir = root / "data" / "raw"
    logger = setup_logging("ingest_report_builder")
    logger.info("Starting Report Builder Excel ingestion...")

    if not force and _file_has_data(out_path):
        rows = len(pd.read_csv(out_path, dtype=str, low_memory=False))
        logger.info(f"  pr_report_builder_master.csv exists ({rows:,} rows) — skipping.")
        return {"rows": rows, "path": str(out_path), "errors": []}

    files = _find_report_builder_files(raw_dir, logger)
    if not files:
        logger.warning("  No Report Builder files found in data/raw/")
        logger.warning("  Expected: 'Report Builder FY20 Revised.xlsx', 'FY_2018_Federal_Procurement_*.xls[x]', etc.")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(columns=MASTER_COLUMNS).to_csv(out_path, index=False, encoding="utf-8")
        return {"rows": 0, "path": str(out_path), "errors": ["No Report Builder files found"]}

    all_dfs = []
    errors = []
    for f in files:
        logger.info(f"  Processing {f.name}...")
        df = _parse_file(f, logger)
        if not df.empty:
            all_dfs.append(df)
        else:
            errors.append(f"No PR rows from {f.name}")

    if not all_dfs:
        logger.warning("  No PR data extracted from any file")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(columns=MASTER_COLUMNS).to_csv(out_path, index=False, encoding="utf-8")
        return {"rows": 0, "path": str(out_path), "errors": errors or ["No data extracted"]}

    combined = pd.concat(all_dfs, ignore_index=True)

    # Deduplicate: same award_id across files (keep last = most recent modification)
    pre_dedup = len(combined)
    if "award_id" in combined.columns:
        combined = combined[combined["award_id"].astype(str).str.strip() != ""]
        combined = combined.drop_duplicates(subset=["award_id"], keep="last")
    logger.info(f"  Dedup: {pre_dedup:,} → {len(combined):,} rows")

    # Ensure all output columns exist
    for col in MASTER_COLUMNS:
        if col not in combined.columns:
            combined[col] = ""

    output = combined[MASTER_COLUMNS]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    output.to_csv(out_path, index=False, encoding="utf-8")

    # Summary
    total = pd.to_numeric(output["obligated_amount"], errors="coerce").fillna(0).sum()
    logger.info("=" * 60)
    logger.info("REPORT BUILDER SUMMARY")
    logger.info("=" * 60)
    logger.info(f"  Files processed:      {len(all_dfs)}")
    logger.info(f"  Total PR rows:        {len(output):,}")
    logger.info(f"  Unique recipients:    {output['recipient_name_normalized'].nunique():,}")
    logger.info(f"  Fiscal years:         {sorted(output['fiscal_year'].dropna().unique().tolist())}")
    logger.info(f"  Total obligated:      ${total:,.0f}")

    return {"rows": len(output), "path": str(out_path), "errors": errors}


def main():
    parser = argparse.ArgumentParser(description="Ingest FPDS Report Builder Excel files for PR")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    result = _run(force=args.force)
    print(f"\nReport Builder ingestion complete: {result['rows']:,} PR contract rows")
    if result["errors"]:
        for e in result["errors"]:
            print(f"  WARNING: {e}")
    return 1 if result["rows"] == 0 else 0


if __name__ == "__main__":
    sys.exit(main())
