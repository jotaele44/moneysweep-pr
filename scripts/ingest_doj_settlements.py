"""
Ingest DOJ / U.S. Attorney (USAO-PR) civil settlements and False Claims Act
recoveries involving Puerto Rico entities from operator-delivered files.

These are published as press releases / litigation reports with no machine API,
so the ingestion path is operator-delivered CSV/Excel until a scraper is built.

Place exports from https://www.justice.gov/ (USAO-PR press releases / FCA recoveries) into:
  data/raw/DOJ_Settlements/

Output:
  data/staging/processed/pr_doj_settlements.csv

Usage:
  python3 scripts/ingest_doj_settlements.py
  python3 scripts/ingest_doj_settlements.py --force
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from contract_sweeper.runtime.dropzone_ingest import ingest_dropzone
from scripts.config import PROJECT_ROOT

RAW_DIR_NAME = "data/raw/DOJ_Settlements"
OUTPUT_PATH = "data/staging/processed/pr_doj_settlements.csv"
KEY_FIELD = "defendant_name"

OUTPUT_COLUMNS = [
    "defendant_name",
    "settlement_amount",
    "settlement_date",
    "agency",
    "case_number",
    "allegation_type",
    "recovery_type",
    "district",
    "source_file",
]

COL_MAP = {
    "defendant_name": ["defendant", "defendant_name", "entity", "demandado", "nombre"],
    "settlement_amount": ["amount", "settlement_amount", "recovery_amount", "monto", "cuantia"],
    "settlement_date": ["date", "settlement_date", "fecha"],
    "agency": ["agency", "department", "agencia"],
    "case_number": ["case_number", "docket", "caso", "numero_caso"],
    "allegation_type": ["allegation", "allegation_type", "claim_type", "tipo"],
    "recovery_type": ["recovery_type", "type", "civil_criminal", "tipo_recobro"],
    "district": ["district", "jurisdiction", "distrito"],
}


def run(root: Path | None = None, force: bool = False) -> dict:
    return ingest_dropzone(
        root=root or PROJECT_ROOT,
        raw_dir_name=RAW_DIR_NAME,
        output_path=OUTPUT_PATH,
        output_columns=OUTPUT_COLUMNS,
        col_map=COL_MAP,
        key_field=KEY_FIELD,
        source_name="ingest_doj_settlements",
        force=force,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="Re-ingest even if output exists")
    args = parser.parse_args()
    result = run(force=args.force)
    print(f"\nDOJ settlements ingest: {result['rows']:,} rows — {result['status']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
