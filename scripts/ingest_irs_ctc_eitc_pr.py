"""
Ingest IRS Child Tax Credit / EITC payments to Puerto Rico families (post-ARPA
expansion) from operator-delivered SOI / Treasury files.

Place exports from https://www.irs.gov/statistics (SOI) / Treasury PR credit reports into:
  data/raw/IRS_CTC_EITC/

Output:
  data/staging/processed/pr_irs_ctc_eitc.csv

Usage:
  python3 scripts/ingest_irs_ctc_eitc_pr.py
  python3 scripts/ingest_irs_ctc_eitc_pr.py --force
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from contract_sweeper.runtime.dropzone_ingest import ingest_dropzone
from scripts.config import PROJECT_ROOT

RAW_DIR_NAME = "data/raw/IRS_CTC_EITC"
OUTPUT_PATH = "data/staging/processed/pr_irs_ctc_eitc.csv"
KEY_FIELD = "program"

OUTPUT_COLUMNS = [
    "tax_year",
    "program",
    "filers_count",
    "total_amount",
    "average_amount",
    "municipality",
    "source_file",
]

COL_MAP = {
    "tax_year": ["tax_year", "year", "ano", "año", "periodo"],
    "program": ["program", "credit", "programa", "tipo"],
    "filers_count": ["filers", "filers_count", "returns", "contribuyentes", "planillas"],
    "total_amount": ["total_amount", "amount", "total", "monto"],
    "average_amount": ["average_amount", "average", "promedio"],
    "municipality": ["municipality", "municipio", "county"],
}


def run(root: Path | None = None, force: bool = False) -> dict:
    return ingest_dropzone(
        root=root or PROJECT_ROOT,
        raw_dir_name=RAW_DIR_NAME,
        output_path=OUTPUT_PATH,
        output_columns=OUTPUT_COLUMNS,
        col_map=COL_MAP,
        key_field=KEY_FIELD,
        source_name="ingest_irs_ctc_eitc_pr",
        force=force,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="Re-ingest even if output exists")
    args = parser.parse_args()
    result = run(force=args.force)
    print(f"\nIRS CTC/EITC ingest: {result['rows']:,} rows — {result['status']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
