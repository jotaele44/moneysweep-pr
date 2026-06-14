"""
Ingest Lotería de Puerto Rico + Lotería Electrónica revenue, prize payouts and
retailer commissions from operator-delivered files.

Place exports from https://www.loteriapr.com/ / Hacienda lottery reports into:
  data/raw/Loteria/

Output:
  data/staging/processed/pr_loteria.csv

Usage:
  python3 scripts/ingest_loteria_pr.py
  python3 scripts/ingest_loteria_pr.py --force
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from contract_sweeper.runtime.dropzone_ingest import ingest_dropzone
from scripts.config import PROJECT_ROOT

RAW_DIR_NAME = "data/raw/Loteria"
OUTPUT_PATH = "data/staging/processed/pr_loteria.csv"
KEY_FIELD = "period"

OUTPUT_COLUMNS = [
    "period",
    "game_type",
    "gross_sales",
    "prizes_paid",
    "commissions_paid",
    "net_to_fund",
    "retailer_count",
    "source_file",
]

COL_MAP = {
    "period": ["periodo", "período", "fecha", "period", "mes", "ano", "año"],
    "game_type": ["juego", "tipo", "game_type", "tipo_loteria", "loteria"],
    "gross_sales": ["ventas", "ventas_brutas", "gross_sales", "sales", "ingresos"],
    "prizes_paid": ["premios", "prizes", "prizes_paid", "premios_pagados"],
    "commissions_paid": ["comisiones", "commissions", "commissions_paid"],
    "net_to_fund": ["neto", "net", "net_to_fund", "aportacion", "aportación"],
    "retailer_count": ["agentes", "detallistas", "retailers", "retailer_count"],
}


def run(root: Path | None = None, force: bool = False) -> dict:
    return ingest_dropzone(
        root=root or PROJECT_ROOT,
        raw_dir_name=RAW_DIR_NAME,
        output_path=OUTPUT_PATH,
        output_columns=OUTPUT_COLUMNS,
        col_map=COL_MAP,
        key_field=KEY_FIELD,
        source_name="ingest_loteria_pr",
        force=force,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="Re-ingest even if output exists")
    args = parser.parse_args()
    result = run(force=args.force)
    print(f"\nLoteria PR ingest: {result['rows']:,} rows — {result['status']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
