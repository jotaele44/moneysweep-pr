"""
Build prasa_contracts_master.csv from pr_prasa_contracts.csv.

Closes a long-standing registry gap: the `prasa` source declared
`prasa_contracts_master.csv` as an expected output with no producer. This
aggregates the ingested PRASA contracts into a vendor-level master (one row per
normalized vendor) so PRASA procurement can be joined like the other master tables.

Input:  data/staging/processed/pr_prasa_contracts.csv
Output: data/staging/processed/prasa_contracts_master.csv

Usage:
  python3 scripts/build_prasa_contracts_master.py [--force]
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from scripts.config import PROJECT_ROOT, setup_logging

MASTER_COLUMNS = [
    "vendor_normalized",
    "vendor_name",
    "contract_count",
    "total_contract_value",
    "first_award_date",
    "last_award_date",
    "agency",
    "source_file",
]


def _file_has_data(path):
    if not path.exists():
        return False
    try:
        return len(pd.read_csv(path, dtype=str, nrows=2)) > 0
    except Exception:
        return False


def run(root=None, force=False):
    root = Path(root or PROJECT_ROOT)
    proc = root / "data" / "staging" / "processed"
    in_path = proc / "pr_prasa_contracts.csv"
    out_path = proc / "prasa_contracts_master.csv"
    logger = setup_logging("build_prasa_contracts_master")

    if not force and _file_has_data(out_path):
        rows = len(pd.read_csv(out_path, dtype=str, low_memory=False))
        logger.info(f"  prasa_contracts_master.csv exists ({rows:,} rows) — skipping.")
        return {"rows": rows, "path": str(out_path), "errors": []}

    out_path.parent.mkdir(parents=True, exist_ok=True)
    if not _file_has_data(in_path):
        logger.warning("  pr_prasa_contracts.csv missing/empty — writing empty master.")
        pd.DataFrame(columns=MASTER_COLUMNS).to_csv(out_path, index=False, encoding="utf-8")
        return {"rows": 0, "path": str(out_path), "errors": ["No PRASA contracts input"]}

    df = pd.read_csv(in_path, dtype=str, na_filter=False, low_memory=False)
    for col in ("vendor_normalized", "vendor_name", "contract_value", "award_date", "source_file"):
        if col not in df.columns:
            df[col] = ""
    df["_value"] = pd.to_numeric(
        df["contract_value"].astype(str).str.replace(r"[^0-9.\-]", "", regex=True),
        errors="coerce",
    ).fillna(0)

    master = (
        df.groupby("vendor_normalized", dropna=False)
        .agg(
            vendor_name=("vendor_name", "first"),
            contract_count=("vendor_normalized", "size"),
            total_contract_value=("_value", "sum"),
            first_award_date=("award_date", "min"),
            last_award_date=("award_date", "max"),
            source_file=("source_file", "first"),
        )
        .reset_index()
    )
    master["agency"] = "AUTORIDAD DE ACUEDUCTOS Y ALCANTARILLADOS"
    master = master[master["vendor_normalized"].astype(str).str.strip() != ""]
    master = master[MASTER_COLUMNS]
    master.to_csv(out_path, index=False, encoding="utf-8")

    logger.info(f"  → {len(master):,} PRASA vendor master rows")
    return {"rows": len(master), "path": str(out_path), "errors": []}


def main():
    parser = argparse.ArgumentParser(description="Build PRASA contracts master")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    result = run(force=args.force)
    print(f"\nPRASA contracts master complete: {result['rows']:,} vendor rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
