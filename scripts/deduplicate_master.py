"""
Merge all normalized expansion CSVs into a single master file and remove
cross-file duplicate records.

Deduplication key: (contract_id, award_date, vendor_name, obligated_amount)
A contract that appears in both a *_direct.csv and *_vendor.csv file will be
reduced to one row. Source file information is preserved as a comma-joined list.

Output: data/staging/processed/pr_contracts_master.csv
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from scripts.config import (
    PROJECT_ROOT,
    setup_logging,
)

DEDUP_COLS = ["contract_id", "award_date", "vendor_name", "obligated_amount"]


def load_all_normalized(root: Path, logger) -> pd.DataFrame:
    """Read all normalized_expansion_*.csv files and concatenate."""
    processed_dir = root / "data" / "staging" / "processed"
    files = sorted(processed_dir.glob("normalized_expansion_*.csv"))

    if not files:
        logger.warning("  No normalized files found in processed/")
        return pd.DataFrame()

    frames = []
    for f in files:
        try:
            df = pd.read_csv(f, dtype=str, low_memory=False)
            frames.append(df)
            logger.debug(f"  Loaded {f.name}: {len(df)} rows")
        except Exception as e:
            logger.warning(f"  Skipping {f.name}: {e}")

    if not frames:
        return pd.DataFrame()

    combined = pd.concat(frames, ignore_index=True)
    logger.info(f"  Loaded {len(files)} files — {len(combined):,} total rows before dedup")
    return combined


def deduplicate(df: pd.DataFrame, logger) -> pd.DataFrame:
    """Drop cross-file duplicate rows based on DEDUP_COLS."""
    if df.empty:
        return df

    present_cols = [c for c in DEDUP_COLS if c in df.columns]

    if not present_cols:
        logger.warning("  No dedup key columns found — skipping deduplication")
        return df

    before = len(df)

    # Where the same contract appears in multiple source files, consolidate
    # the source_file column into a comma-joined string before dropping dupes.
    if "source_file" in df.columns and present_cols:
        df["source_file"] = df.groupby(present_cols, sort=False)["source_file"].transform(
            lambda x: ",".join(sorted(set(x.dropna().astype(str))))
        )

    df = df.drop_duplicates(subset=present_cols, keep="first")
    removed = before - len(df)

    if removed:
        logger.info(f"  Removed {removed:,} cross-file duplicate rows")
    else:
        logger.info("  No cross-file duplicates found")

    return df


def main(root: Path = None) -> dict:
    """Build and write pr_contracts_master.csv. Returns stats dict."""
    if root is None:
        root = PROJECT_ROOT

    logger = setup_logging("deduplicate_master")
    logger.info("Building consolidated master file...")

    df = load_all_normalized(root, logger)

    if df.empty:
        logger.warning("  No data to merge — master not written")
        return {"master_rows": 0, "duplicates_removed": 0, "output_path": None}

    before = len(df)
    df = deduplicate(df, logger)
    removed = before - len(df)

    master_path = root / "data" / "staging" / "processed" / "pr_contracts_master.csv"
    master_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(master_path, index=False, encoding="utf-8")

    logger.info(f"  Master written: {len(df):,} rows → {master_path.name}")

    return {
        "master_rows": len(df),
        "duplicates_removed": removed,
        "output_path": master_path,
    }


if __name__ == "__main__":
    stats = main()
    print(
        f"\nMaster: {stats['master_rows']:,} rows ({stats['duplicates_removed']:,} duplicates removed)"
    )
    print(f"Output: {stats['output_path']}")
