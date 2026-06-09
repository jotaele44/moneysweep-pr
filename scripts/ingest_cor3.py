"""
Ingest COR3 (Central Office for Recovery, Reconstruction and Resiliency)
Transparency Portal Excel exports.

Place COR3 Transparency Portal Excel exports into data/raw/COR3/:
  COR3 Transparency Portal_Financial_Summary_*.xlsx
  COR3 Transparency Portal_Procurement Inventory_*.xlsx
  COR3 Transparency Portal_RFP and Contracts_*.xlsx

Output (same schema as download_cor3.py):
  data/staging/processed/pr_cor3_projects.csv

Usage:
  python3 scripts/ingest_cor3.py
  python3 scripts/ingest_cor3.py --force
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from scripts.config import PROJECT_ROOT, setup_logging

RAW_DIR = PROJECT_ROOT / "data" / "raw" / "COR3"

OUTPUT_COLUMNS = [
    "project_id",
    "applicant_name",
    "applicant_normalized",
    "program",
    "category",
    "municipality",
    "total_approved",
    "total_disbursed",
    "disbursement_rate",
    "status",
    "last_updated",
]

COL_MAP = {
    "project_id": [
        "Project ID",
        "project_id",
        "ID",
        "Project Number",
        "Project #",
        "Project No",
        "Num",
        "Number",
        "PA Project Number",
        "PW Number",
        "Contract Number",
        "Contract No",
        "Contract #",
    ],
    "applicant_name": [
        "Applicant",
        "Applicant Name",
        "Subrecipient",
        "Subrecipient Name",
        "Contractor",
        "Contractor Name",
        "Vendor",
        "Vendor Name",
        "Prime Contractor",
        "Awardee",
        "Organization",
        "Entity Name",
    ],
    "program": [
        "Program",
        "Program Type",
        "Fund",
        "Funding Source",
        "FEMA Program",
        "Grant Program",
        "Funding Program",
        "Program Name",
        "Source of Funds",
    ],
    "category": [
        "Category",
        "Work Type",
        "Project Category",
        "Category of Work",
        "Type of Work",
        "Work Category",
        "Project Type",
        "Type",
        "Category Name",
        "Procurement Category",
    ],
    "municipality": [
        "Municipality",
        "Municipio",
        "Location",
        "City",
        "Jurisdiccion",
        "Jurisdiction",
        "Town",
        "Place of Performance",
    ],
    "total_approved": [
        "Total Approved",
        "Approved Amount",
        "Total Award",
        "Award Amount",
        "Contract Value",
        "Obligated Amount",
        "Eligible Cost",
        "Total Eligible",
        "Authorized Amount",
        "Budget",
    ],
    "total_disbursed": [
        "Total Disbursed",
        "Disbursed",
        "Paid",
        "Total Paid",
        "Amount Paid",
        "Payments",
        "Drawn",
        "Amount Drawn",
        "Total Drawn",
        "Disbursements",
    ],
    "status": ["Status", "Project Status", "Estado", "Current Status"],
    "last_updated": [
        "Last Updated",
        "Date",
        "Updated",
        "Report Date",
        "As of Date",
        "Data Date",
        "Date Updated",
    ],
}

_STRIP_RE = re.compile(r"[^\w\s]")
_SPACE_RE = re.compile(r"\s+")
_SUFFIXES = {"INC", "LLC", "LLP", "CORP", "CO", "LTD", "LP", "SA", "SRL"}


def _normalize_name(name: str) -> str:
    if not name or pd.isna(name):
        return ""
    n = _STRIP_RE.sub(" ", str(name).upper())
    n = _SPACE_RE.sub(" ", n).strip()
    tokens = n.split()
    while tokens and tokens[-1] in _SUFFIXES:
        tokens.pop()
    return " ".join(tokens)


def _map_col(df: pd.DataFrame, candidates: list) -> str | None:
    df_lower = {c.lower().strip(): c for c in df.columns}
    for cand in candidates:
        actual = df_lower.get(cand.lower().strip())
        if actual is not None:
            return actual
    return None


def _to_numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(
        series.astype(str).str.replace(r"[$,\s]", "", regex=True),
        errors="coerce",
    )


def _parse_sheet(df: pd.DataFrame, source_file: str) -> pd.DataFrame:
    """Map one sheet to OUTPUT_COLUMNS. Returns empty DataFrame if no useful columns found."""
    out = {}
    matched = 0
    for target, candidates in COL_MAP.items():
        src_col = _map_col(df, candidates)
        if src_col is not None:
            out[target] = df[src_col].astype(str).str.strip()
            matched += 1
        else:
            out[target] = ""

    # Need at least applicant + one amount column to be useful
    if matched < 2:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    out_df = pd.DataFrame(out)

    # Normalize entity name
    out_df["applicant_normalized"] = out_df["applicant_name"].apply(_normalize_name)

    # Compute disbursement rate
    approved = _to_numeric(out_df["total_approved"])
    disbursed = _to_numeric(out_df["total_disbursed"])
    out_df["total_approved"] = approved.fillna(0).astype(str)
    out_df["total_disbursed"] = disbursed.fillna(0).astype(str)
    rate = (disbursed / approved.replace(0, pd.NA)).round(4)
    out_df["disbursement_rate"] = rate.astype(str)

    # Drop rows where all key fields are blank/zero
    key_cols = ["project_id", "applicant_name", "total_approved"]
    mask = (
        out_df[key_cols]
        .apply(lambda col: col.str.strip().isin(["", "0", "0.0", "nan"]))
        .all(axis=1)
    )
    out_df = out_df[~mask]

    for col in OUTPUT_COLUMNS:
        if col not in out_df.columns:
            out_df[col] = ""

    return out_df[OUTPUT_COLUMNS]


def run(root: Path | None = None, force: bool = False) -> dict:
    if root is None:
        root = PROJECT_ROOT
    root = Path(root)
    raw_dir = root / "data" / "raw" / "COR3"
    out_path = root / "data" / "staging" / "processed" / "pr_cor3_projects.csv"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    logger = setup_logging("ingest_cor3")

    if not force and out_path.exists():
        existing = pd.read_csv(out_path, dtype=str, low_memory=False)
        if len(existing) > 0:
            logger.info(f"  Cached — {len(existing):,} rows in {out_path.name}")
            return {"rows": len(existing), "path": str(out_path), "status": "CACHED"}

    if not raw_dir.exists():
        logger.info(f"  No COR3 raw dir at {raw_dir} — skipping ingest")
        return {"rows": 0, "path": str(out_path), "status": "NO_FILES"}

    xlsx_files = sorted(raw_dir.glob("*.xlsx")) + sorted(raw_dir.glob("*.xls"))
    if not xlsx_files:
        logger.info(f"  No Excel files in {raw_dir} — skipping ingest")
        return {"rows": 0, "path": str(out_path), "status": "NO_FILES"}

    logger.info(f"  Found {len(xlsx_files)} COR3 Excel file(s) in {raw_dir}")
    frames = []
    for f in xlsx_files:
        logger.info(f"  Reading {f.name}...")
        try:
            xl = pd.ExcelFile(f)
            for sheet in xl.sheet_names:
                try:
                    df = xl.parse(sheet, dtype=str)
                    if df.empty or len(df.columns) < 3:
                        continue
                    parsed = _parse_sheet(df, f.name)
                    if not parsed.empty:
                        logger.info(f"    Sheet '{sheet}': {len(parsed):,} rows")
                        frames.append(parsed)
                except Exception as e:
                    logger.warning(f"    Sheet '{sheet}' error: {e}")
        except Exception as e:
            logger.warning(f"  Could not open {f.name}: {e}")

    if not frames:
        logger.warning("  No parseable COR3 Excel data found — writing empty schema")
        pd.DataFrame(columns=OUTPUT_COLUMNS).to_csv(out_path, index=False, encoding="utf-8")
        return {"rows": 0, "path": str(out_path), "status": "EMPTY"}

    combined = pd.concat(frames, ignore_index=True)

    # Deduplicate on project_id where non-empty
    before = len(combined)
    has_id = combined["project_id"].str.strip().ne("")
    deduped_with_id = combined[has_id].drop_duplicates(subset=["project_id"], keep="first")
    no_id = combined[~has_id]
    combined = pd.concat([deduped_with_id, no_id], ignore_index=True)
    removed = before - len(combined)
    if removed:
        logger.info(f"  Removed {removed:,} duplicate project_id rows")

    combined.to_csv(out_path, index=False, encoding="utf-8")
    logger.info(f"  Written: {out_path.name} ({len(combined):,} rows)")
    return {"rows": len(combined), "path": str(out_path), "status": "OK"}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Ingest COR3 Transparency Portal Excel exports from data/raw/COR3/"
    )
    parser.add_argument("--force", action="store_true", help="Re-ingest even if output exists")
    args = parser.parse_args()
    result = run(force=args.force)
    print(f"\nCOR3 ingest: {result['rows']:,} rows — {result['status']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
