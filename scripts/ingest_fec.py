"""
Ingest FEC contribution data exported from the FEC website.

Place one or more CSV files exported from:
  https://www.fec.gov/data/receipts/?data_type=efiling&contributor_state=PR

into  data/raw/FEC/

The FEC website "Download" button produces a CSV with these columns
(exact set depends on export format, so the mapper is flexible):

  committee_id, committee_name, image_num, entity_type,
  contributor_name, contributor_street_1, contributor_street_2,
  contributor_city, contributor_state, contributor_zip,
  contributor_employer, contributor_occupation,
  contribution_receipt_date, contribution_receipt_amount,
  report_type, report_year, two_year_transaction_period,
  memo_text, candidate_id, candidate_name, file_number,
  amendment_indicator, sub_id, ...

Output (same schema as download_fec.py):
  data/staging/processed/pr_fec_contributions.csv

Usage:
  python3 scripts/ingest_fec.py
  python3 scripts/ingest_fec.py --force
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from scripts.config import PROJECT_ROOT, setup_logging

RAW_DIR_NAME = "data/raw/FEC"

OUTPUT_COLUMNS = [
    "cycle",
    "contributor_name",
    "contributor_city",
    "contributor_zip_code",
    "contributor_employer",
    "contributor_occupation",
    "contribution_receipt_amount",
    "contribution_receipt_date",
    "committee_id",
    "committee_name",
    "candidate_id",
    "candidate_name",
    "report_year",
    "election_type",
    "memo_text",
    "is_individual",
]

# Column name candidates for each output field (tried in order, first match wins)
COL_MAP = {
    "cycle":                        ["two_year_transaction_period", "cycle", "report_year"],
    "contributor_name":             ["contributor_name", "contributor name", "name"],
    "contributor_city":             ["contributor_city", "contributor city", "city"],
    "contributor_zip_code":         ["contributor_zip", "contributor_zip_code", "zip_code", "zip"],
    "contributor_employer":         ["contributor_employer", "employer"],
    "contributor_occupation":       ["contributor_occupation", "occupation"],
    "contribution_receipt_amount":  ["contribution_receipt_amount", "amount", "contribution_amount"],
    "contribution_receipt_date":    ["contribution_receipt_date", "date", "receipt_date"],
    "committee_id":                 ["committee_id", "fec_committee_id", "cmte_id"],
    "committee_name":               ["committee_name", "committee name", "cmte_name"],
    "candidate_id":                 ["candidate_id", "cand_id"],
    "candidate_name":               ["candidate_name", "candidate name"],
    "report_year":                  ["report_year", "rpt_yr"],
    "election_type":                ["election_type", "election type", "form_type"],
    "memo_text":                    ["memo_text", "memo text", "memo_cd", "memo"],
    "is_individual":                ["entity_type", "entity type"],
}


def _derive_fiscal_year(date_str: str) -> str:
    """Derive FEC two-year cycle from a contribution date."""
    if not date_str or pd.isna(date_str):
        return ""
    try:
        d = pd.to_datetime(str(date_str), errors="coerce")
        if pd.isna(d):
            return ""
        # FEC cycle = even year ending the two-year period
        year = d.year
        return str(year if year % 2 == 0 else year + 1)
    except Exception:
        return ""


def _map_col(df: pd.DataFrame, candidates: list[str]):
    """Return the first column name from candidates that exists in df, or None."""
    df_lower = {c.lower().strip(): c for c in df.columns}
    for cand in candidates:
        actual = df_lower.get(cand.lower().strip())
        if actual is not None:
            return actual
    return None


def _parse_df(df: pd.DataFrame, source_file: str) -> pd.DataFrame:
    """Map a raw FEC export DataFrame to the canonical OUTPUT_COLUMNS schema."""
    out = {}
    for target, candidates in COL_MAP.items():
        src_col = _map_col(df, candidates)
        if src_col is not None:
            out[target] = df[src_col].astype(str).str.strip()
        else:
            out[target] = ""

    out_df = pd.DataFrame(out)

    # Normalize is_individual: "IND" → True, else False
    if _map_col(df, ["entity_type", "entity type"]) is not None:
        out_df["is_individual"] = out_df["is_individual"].str.upper().str.strip() == "IND"
    else:
        out_df["is_individual"] = False

    # Derive cycle if missing
    if out_df["cycle"].eq("").all() or out_df["cycle"].isna().all():
        out_df["cycle"] = out_df["contribution_receipt_date"].apply(_derive_fiscal_year)

    # Filter to PR only (in case the export covers other states)
    state_col = _map_col(df, ["contributor_state", "contributor state", "state"])
    if state_col is not None:
        pr_mask = df[state_col].str.upper().str.strip().isin(["PR", "PUERTO RICO"])
        out_df = out_df[pr_mask.values]

    for col in OUTPUT_COLUMNS:
        if col not in out_df.columns:
            out_df[col] = ""

    return out_df[OUTPUT_COLUMNS]


def run(root: Path = None, force: bool = False) -> dict:
    if root is None:
        root = PROJECT_ROOT
    root = Path(root)
    raw_dir = root / RAW_DIR_NAME
    out_path = root / "data" / "staging" / "processed" / "pr_fec_contributions.csv"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    logger = setup_logging("ingest_fec")

    if not force and out_path.exists():
        existing = pd.read_csv(out_path, dtype=str, low_memory=False)
        if len(existing) > 0:
            logger.info(f"  Cached — {len(existing):,} rows in {out_path.name}")
            return {"rows": len(existing), "path": str(out_path), "status": "CACHED"}

    if not raw_dir.exists():
        logger.info(f"  No FEC raw dir at {raw_dir} — skipping ingest")
        return {"rows": 0, "path": str(out_path), "status": "NO_FILES"}

    csv_files = sorted(raw_dir.glob("*.csv"))
    if not csv_files:
        logger.info(f"  No CSV files in {raw_dir} — skipping ingest")
        return {"rows": 0, "path": str(out_path), "status": "NO_FILES"}

    logger.info(f"  Found {len(csv_files)} FEC export file(s) in {raw_dir}")
    frames = []
    for f in csv_files:
        logger.info(f"  Reading {f.name}...")
        try:
            df = pd.read_csv(f, dtype=str, low_memory=False)
            logger.info(f"    {len(df):,} rows, columns: {list(df.columns[:6])}")
            parsed = _parse_df(df, f.name)
            logger.info(f"    → {len(parsed):,} PR rows after mapping")
            frames.append(parsed)
        except Exception as e:
            logger.warning(f"  Could not parse {f.name}: {e}")

    if not frames:
        logger.warning("  No parseable FEC export files found")
        return {"rows": 0, "path": str(out_path), "status": "EMPTY"}

    combined = pd.concat(frames, ignore_index=True)

    # Deduplicate on the same key as download_fec.py
    before = len(combined)
    combined = combined.drop_duplicates(
        subset=["contributor_name", "committee_id",
                "contribution_receipt_date", "contribution_receipt_amount"],
        keep="first",
    )
    removed = before - len(combined)
    if removed:
        logger.info(f"  Removed {removed:,} duplicate rows")

    combined.to_csv(out_path, index=False, encoding="utf-8")
    logger.info(f"  Written: {out_path.name} ({len(combined):,} rows)")
    return {"rows": len(combined), "path": str(out_path), "status": "OK"}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Ingest FEC contribution CSV exports from data/raw/FEC/"
    )
    parser.add_argument("--force", action="store_true", help="Re-ingest even if output exists")
    args = parser.parse_args()
    result = run(force=args.force)
    print(f"\nFEC ingest: {result['rows']:,} rows — {result['status']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
