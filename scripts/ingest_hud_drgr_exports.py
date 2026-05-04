"""
Load authorized local HUD DRGR exports from data/raw/HUD DRGR/ or data/raw/HUD/.

These are files manually exported from the DRGR portal by authorized users.
No credential automation — this script only reads files already on disk.

Outputs:
  data/normalized/hud_drgr_activities.parquet
  data/normalized/hud_drgr_drawdowns.parquet
  data/normalized/hud_drgr_appropriations.parquet

Usage:
  python3 scripts/ingest_hud_drgr_exports.py
  python3 scripts/ingest_hud_drgr_exports.py --force
"""

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from scripts.build_unified_master import _normalize_name
from scripts.config import PROJECT_ROOT, setup_logging

NORMALIZED_DIR = PROJECT_ROOT / "data" / "normalized"

RAW_DIRS = [
    PROJECT_ROOT / "data" / "raw" / "HUD DRGR",
    PROJECT_ROOT / "data" / "raw" / "HUD",
    PROJECT_ROOT / "data" / "raw" / "hud_drgr",
    PROJECT_ROOT / "data" / "raw" / "hud",
]

ACTIVITY_COLUMNS = [
    "activity_id", "grant_number", "project_id",
    "activity_name", "activity_type", "status",
    "responsible_org", "responsible_org_normalized",
    "address", "municipality", "county",
    "national_objective", "benefit_type",
    "total_budget", "amount_drawn", "amount_remaining",
    "start_date", "end_date",
    "source_file",
]

DRAWDOWN_COLUMNS = [
    "drawdown_id", "grant_number", "activity_id",
    "drawdown_date", "drawdown_amount",
    "cumulative_drawn", "remaining_budget",
    "source_file",
]

APPROPRIATION_COLUMNS = [
    "appropriation_id", "grant_number", "program_type",
    "appropriation_year", "appropriation_amount",
    "allocation_date", "grantee_name", "grantee_normalized",
    "cfda_number", "source_file",
]

# Flexible column maps for each category
ACTIVITY_COL_MAP = {
    "activity_id":   ["Activity ID", "Activity Number", "Activity #", "activity_id", "id"],
    "grant_number":  ["Grant Number", "Grant #", "CDBG Grant", "grant_number", "Grant"],
    "project_id":    ["Project ID", "Project Number", "Project #", "project_id"],
    "activity_name": ["Activity Name", "Activity Description", "Name", "activity_name"],
    "activity_type": ["Activity Type", "Type", "Category", "activity_type"],
    "status":        ["Status", "Activity Status", "Current Status", "status"],
    "responsible_org": ["Responsible Organization", "Responsible Org", "Organization", "Subrecipient", "responsible_org"],
    "address":       ["Address", "Location", "Site Address", "address"],
    "municipality":  ["Municipality", "City", "Locality", "municipality"],
    "county":        ["County", "county"],
    "national_objective": ["National Objective", "HUD National Objective", "Objective", "national_objective"],
    "benefit_type":  ["Benefit Type", "Benefit", "LMI", "benefit_type"],
    "total_budget":  ["Total Budget", "Budget Amount", "Allocation", "Approved Amount", "total_budget"],
    "amount_drawn":  ["Amount Drawn", "Drawn", "Disbursed", "Expended", "amount_drawn"],
    "amount_remaining": ["Amount Remaining", "Balance", "Remaining", "amount_remaining"],
    "start_date":    ["Start Date", "Begin Date", "start_date"],
    "end_date":      ["End Date", "Completion Date", "end_date"],
}

DRAWDOWN_COL_MAP = {
    "drawdown_id":    ["Drawdown ID", "Draw ID", "Transaction ID", "drawdown_id"],
    "grant_number":   ["Grant Number", "Grant #", "grant_number"],
    "activity_id":    ["Activity ID", "Activity Number", "activity_id"],
    "drawdown_date":  ["Drawdown Date", "Date", "Transaction Date", "drawdown_date"],
    "drawdown_amount": ["Drawdown Amount", "Amount", "Draw Amount", "drawdown_amount"],
    "cumulative_drawn": ["Cumulative Drawn", "Cumulative", "Total Drawn", "cumulative_drawn"],
    "remaining_budget": ["Remaining Budget", "Balance", "remaining_budget"],
}

APPROPRIATION_COL_MAP = {
    "appropriation_id":     ["Appropriation ID", "ID", "appropriation_id"],
    "grant_number":         ["Grant Number", "Grant", "grant_number"],
    "program_type":         ["Program Type", "Program", "Type", "program_type"],
    "appropriation_year":   ["Year", "Appropriation Year", "FY", "appropriation_year"],
    "appropriation_amount": ["Amount", "Appropriation Amount", "Total Amount", "appropriation_amount"],
    "allocation_date":      ["Date", "Allocation Date", "allocation_date"],
    "grantee_name":         ["Grantee Name", "Grantee", "Recipient", "grantee_name"],
    "cfda_number":          ["CFDA", "CFDA Number", "Assistance Listing", "cfda_number"],
}

CLASSIFY_KEYWORDS = {
    "drawdowns": ["drawdown", "draw ", "disbursement", "payment", "transaction"],
    "activities": ["activit", "project_list", "projectlist"],
    "appropriations": ["appropriat", "allocation", " grant list", "grantlist"],
}


def _map_col(df_cols, candidates):
    cols_lower = {c.lower().strip(): c for c in df_cols}
    for cand in candidates:
        if cand in df_cols:
            return cand
        if cand.lower() in cols_lower:
            return cols_lower[cand.lower()]
    return None


def _read_file(path, logger):
    suffix = path.suffix.lower()
    try:
        if suffix in (".xlsx", ".xls"):
            xl = pd.ExcelFile(path)
            best = pd.DataFrame()
            for sheet in xl.sheet_names:
                try:
                    df = pd.read_excel(xl, sheet_name=sheet, dtype=str, na_filter=False)
                    if len(df) > len(best):
                        best = df
                except Exception:
                    pass
            return best
        elif suffix == ".csv":
            for enc in ("utf-8", "latin-1", "cp1252"):
                try:
                    return pd.read_csv(path, dtype=str, na_filter=False, encoding=enc, low_memory=False)
                except UnicodeDecodeError:
                    continue
    except Exception as e:
        logger.warning(f"  Failed to read {path.name}: {e}")
    return pd.DataFrame()


def _classify(path, df):
    name = path.stem.lower()
    col_names = " ".join(c.lower() for c in df.columns)
    combined = name + " " + col_names
    scores = {}
    for category, keywords in CLASSIFY_KEYWORDS.items():
        scores[category] = sum(1 for kw in keywords if kw in combined)
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "activities"


def _map_to_schema(df, col_map, columns, source_file):
    out = {}
    for out_col, candidates in col_map.items():
        src = _map_col(df.columns.tolist(), candidates)
        out[out_col] = df[src] if src else ""
    result = pd.DataFrame(out)
    result["source_file"] = source_file
    for col in columns:
        if col not in result.columns:
            result[col] = ""
    return result[columns]


def _find_raw_files(logger):
    found = []
    for raw_dir in RAW_DIRS:
        if not raw_dir.exists():
            continue
        for pattern in ("*.xlsx", "*.xls", "*.csv"):
            for f in raw_dir.glob(pattern):
                if not f.name.startswith("."):
                    found.append(f)
        # One level deep
        for sub in raw_dir.iterdir():
            if sub.is_dir():
                for pattern in ("*.xlsx", "*.xls", "*.csv"):
                    for f in sub.glob(pattern):
                        if not f.name.startswith("."):
                            found.append(f)
    logger.info(f"  Found {len(found)} HUD DRGR export files")
    return sorted(set(found))


def run(root=None, force=False):
    root = Path(root or PROJECT_ROOT)
    norm_dir = root / "data" / "normalized"
    norm_dir.mkdir(parents=True, exist_ok=True)

    activity_path     = norm_dir / "hud_drgr_activities.parquet"
    drawdown_path     = norm_dir / "hud_drgr_drawdowns.parquet"
    appropriation_path = norm_dir / "hud_drgr_appropriations.parquet"
    logger = setup_logging("ingest_hud_drgr_exports")

    if not force and all(p.exists() for p in [activity_path, drawdown_path, appropriation_path]):
        a_rows = len(pd.read_parquet(activity_path, engine="pyarrow"))
        logger.info(f"  HUD DRGR exports: {a_rows:,} activities — skipping (use --force).")
        return {"activity_rows": a_rows, "drawdown_rows": 0, "appropriation_rows": 0, "status": "CACHED"}

    files = _find_raw_files(logger)

    activity_dfs, drawdown_dfs, appropriation_dfs = [], [], []

    for f in files:
        logger.info(f"  Processing {f.name}...")
        df = _read_file(f, logger)
        if df.empty:
            continue
        cat = _classify(f, df)
        logger.info(f"    → classified as: {cat} ({len(df):,} rows)")
        if cat == "drawdowns":
            mapped = _map_to_schema(df, DRAWDOWN_COL_MAP, DRAWDOWN_COLUMNS, f.name)
            drawdown_dfs.append(mapped)
        elif cat == "appropriations":
            mapped = _map_to_schema(df, APPROPRIATION_COL_MAP, APPROPRIATION_COLUMNS, f.name)
            appropriation_dfs.append(mapped)
        else:
            mapped = _map_to_schema(df, ACTIVITY_COL_MAP, ACTIVITY_COLUMNS, f.name)
            if "responsible_org" in mapped.columns:
                mapped["responsible_org_normalized"] = mapped["responsible_org"].apply(_normalize_name)
            activity_dfs.append(mapped)

    def _save(dfs, columns, path, label):
        if dfs:
            combined = pd.concat(dfs, ignore_index=True)
            combined.to_parquet(path, index=False, engine="pyarrow")
            n = len(combined)
        else:
            logger.warning(f"  No {label} data found — writing empty parquet")
            pd.DataFrame(columns=columns).to_parquet(path, index=False, engine="pyarrow")
            n = 0
        logger.info(f"  {label}: {n:,} rows → {path.name}")
        return n

    a_rows = _save(activity_dfs,     ACTIVITY_COLUMNS,     activity_path,     "activities")
    d_rows = _save(drawdown_dfs,     DRAWDOWN_COLUMNS,     drawdown_path,     "drawdowns")
    p_rows = _save(appropriation_dfs, APPROPRIATION_COLUMNS, appropriation_path, "appropriations")

    return {"activity_rows": a_rows, "drawdown_rows": d_rows, "appropriation_rows": p_rows, "status": "OK"}


def main():
    parser = argparse.ArgumentParser(description="Ingest HUD DRGR local export files")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    result = run(force=args.force)
    print(f"\nHUD DRGR exports: {result['activity_rows']:,} activities, "
          f"{result['drawdown_rows']:,} drawdowns, {result['appropriation_rows']:,} appropriations")
    return 0


if __name__ == "__main__":
    sys.exit(main())
