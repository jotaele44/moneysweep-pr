"""
Ingest DTOP vehicle-registration (marbete) and license fee collections from
operator-delivered files.

Place exports from https://www.dtop.pr.gov/ (vehicle registration / marbete) into:
  data/raw/DTOP/

Output:
  data/staging/processed/pr_dtop_fees.csv

Usage:
  python3 scripts/ingest_dtop_vehicle_fees.py
  python3 scripts/ingest_dtop_vehicle_fees.py --force
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from moneysweep.runtime.dropzone_ingest import ingest_dropzone
from scripts.config import PROJECT_ROOT

RAW_DIR_NAME = "data/raw/DTOP"
OUTPUT_PATH = "data/staging/processed/pr_dtop_fees.csv"
KEY_FIELD = "transaction_type"

OUTPUT_COLUMNS = [
    "transaction_type",
    "category",
    "fee_amount",
    "count",
    "fiscal_year",
    "region",
    "source_file",
]

COL_MAP = {
    "transaction_type": [
        "tipo_transaccion",
        "tipo_transacción",
        "transaction_type",
        "tipo",
        "transaccion",
        "transacción",
    ],
    "category": ["categoria", "categoría", "category", "clase", "clasificacion", "clasificación"],
    "fee_amount": ["derechos", "fee", "fee_amount", "monto", "arancel", "cantidad"],
    "count": ["cantidad", "count", "conteo", "numero", "número", "total"],
    "fiscal_year": ["ano_fiscal", "año_fiscal", "fiscal_year", "year"],
    "region": ["region", "región", "area", "área", "oficina"],
}


def run(root: Path | None = None, force: bool = False) -> dict:
    return ingest_dropzone(
        root=root or PROJECT_ROOT,
        raw_dir_name=RAW_DIR_NAME,
        output_path=OUTPUT_PATH,
        output_columns=OUTPUT_COLUMNS,
        col_map=COL_MAP,
        key_field=KEY_FIELD,
        source_name="ingest_dtop_vehicle_fees",
        force=force,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="Re-ingest even if output exists")
    args = parser.parse_args()
    result = run(force=args.force)
    print(f"\nDTOP vehicle fees ingest: {result['rows']:,} rows — {result['status']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
