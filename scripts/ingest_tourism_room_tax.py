"""
Ingest PR Tourism Company hotel-occupancy tax (impuesto de ocupación) and
co-op marketing contributions from operator-delivered files.

Place exports from https://www.discoverpuertorico.com / PR Tourism Company reports into:
  data/raw/Tourism/

Output:
  data/staging/processed/pr_tourism_roomtax.csv

Usage:
  python3 scripts/ingest_tourism_room_tax.py
  python3 scripts/ingest_tourism_room_tax.py --force
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from moneysweep.runtime.dropzone_ingest import ingest_dropzone
from scripts.config import PROJECT_ROOT

RAW_DIR_NAME = "data/raw/Tourism"
OUTPUT_PATH = "data/staging/processed/pr_tourism_roomtax.csv"
KEY_FIELD = "period"

OUTPUT_COLUMNS = [
    "period",
    "taxpayer_name",
    "municipality",
    "room_tax_collected",
    "contract_type",
    "marketing_contribution",
    "source_file",
]

COL_MAP = {
    "period": ["periodo", "período", "period", "fecha", "mes", "ano", "año"],
    "taxpayer_name": [
        "hospederia",
        "hospedería",
        "hotel",
        "taxpayer",
        "taxpayer_name",
        "nombre",
        "contribuyente",
    ],
    "municipality": ["municipio", "municipality", "pueblo", "region", "región"],
    "room_tax_collected": [
        "impuesto",
        "room_tax",
        "room_tax_collected",
        "ocupacion",
        "ocupación",
        "recaudo",
    ],
    "contract_type": ["tipo_contrato", "contract_type", "tipo", "acuerdo"],
    "marketing_contribution": [
        "aportacion",
        "aportación",
        "marketing",
        "marketing_contribution",
        "coop",
    ],
}


def run(root: Path | None = None, force: bool = False) -> dict:
    return ingest_dropzone(
        root=root or PROJECT_ROOT,
        raw_dir_name=RAW_DIR_NAME,
        output_path=OUTPUT_PATH,
        output_columns=OUTPUT_COLUMNS,
        col_map=COL_MAP,
        key_field=KEY_FIELD,
        source_name="ingest_tourism_room_tax",
        force=force,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="Re-ingest even if output exists")
    args = parser.parse_args()
    result = run(force=args.force)
    print(f"\nTourism room tax ingest: {result['rows']:,} rows — {result['status']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
