"""
Ingest DOJ / Treasury equitable-sharing asset-forfeiture payouts to Puerto Rico
law-enforcement agencies from operator-delivered files.

Place exports from https://www.justice.gov/afp (DOJ) and Treasury equitable-sharing reports into:
  data/raw/Equitable_Sharing/

Output:
  data/staging/processed/pr_equitable_sharing.csv

Usage:
  python3 scripts/ingest_equitable_sharing.py
  python3 scripts/ingest_equitable_sharing.py --force
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from moneysweep.runtime.dropzone_ingest import ingest_dropzone
from scripts.config import PROJECT_ROOT

RAW_DIR_NAME = "data/raw/Equitable_Sharing"
OUTPUT_PATH = "data/staging/processed/pr_equitable_sharing.csv"
KEY_FIELD = "recipient_agency"

OUTPUT_COLUMNS = [
    "recipient_agency",
    "state",
    "equitable_sharing_amount",
    "fiscal_year",
    "asset_type",
    "program",
    "source_file",
]

COL_MAP = {
    "recipient_agency": ["agency", "recipient_agency", "department", "agencia", "recipient"],
    "state": ["state", "estado"],
    "equitable_sharing_amount": ["amount", "equitable_sharing_amount", "payment", "monto"],
    "fiscal_year": ["fiscal_year", "fy", "year", "ano", "año"],
    "asset_type": ["asset_type", "type", "tipo_activo"],
    "program": ["program", "doj_treasury", "programa"],
}


def run(root: Path | None = None, force: bool = False) -> dict:
    return ingest_dropzone(
        root=root or PROJECT_ROOT,
        raw_dir_name=RAW_DIR_NAME,
        output_path=OUTPUT_PATH,
        output_columns=OUTPUT_COLUMNS,
        col_map=COL_MAP,
        key_field=KEY_FIELD,
        source_name="ingest_equitable_sharing",
        force=force,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="Re-ingest even if output exists")
    args = parser.parse_args()
    result = run(force=args.force)
    print(f"\nEquitable sharing ingest: {result['rows']:,} rows — {result['status']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
