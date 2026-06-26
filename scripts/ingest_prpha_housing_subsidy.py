"""
Ingest PR Public Housing Administration (AVP / PRPHA) operating subsidies and
RAD conversions from operator-delivered files. Distinct from HUD Section-8 HCV.

Place exports from https://www.avp.pr.gov / HUD (public housing operating subsidies & RAD) into:
  data/raw/PRPHA/

Output:
  data/staging/processed/pr_prpha_subsidies.csv

Usage:
  python3 scripts/ingest_prpha_housing_subsidy.py
  python3 scripts/ingest_prpha_housing_subsidy.py --force
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from moneysweep.runtime.dropzone_ingest import ingest_dropzone
from scripts.config import PROJECT_ROOT

RAW_DIR_NAME = "data/raw/PRPHA"
OUTPUT_PATH = "data/staging/processed/pr_prpha_subsidies.csv"
KEY_FIELD = "project_name"

OUTPUT_COLUMNS = [
    "project_name",
    "development_id",
    "subsidy_type",
    "subsidy_amount",
    "units",
    "municipality",
    "fiscal_year",
    "source_file",
]

COL_MAP = {
    "project_name": ["residencial", "proyecto", "project", "project_name", "nombre", "development"],
    "development_id": ["id", "development_id", "numero", "número", "ampi", "codigo", "código"],
    "subsidy_type": ["tipo", "subsidy_type", "tipo_subsidio", "programa", "operating_rad"],
    "subsidy_amount": ["monto", "subsidy_amount", "amount", "subsidio", "cantidad"],
    "units": ["unidades", "units", "viviendas", "apartamentos"],
    "municipality": ["municipio", "municipality", "pueblo"],
    "fiscal_year": ["ano_fiscal", "año_fiscal", "fiscal_year", "year"],
}


def run(root: Path | None = None, force: bool = False) -> dict:
    return ingest_dropzone(
        root=root or PROJECT_ROOT,
        raw_dir_name=RAW_DIR_NAME,
        output_path=OUTPUT_PATH,
        output_columns=OUTPUT_COLUMNS,
        col_map=COL_MAP,
        key_field=KEY_FIELD,
        source_name="ingest_prpha_housing_subsidy",
        force=force,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="Re-ingest even if output exists")
    args = parser.parse_args()
    result = run(force=args.force)
    print(f"\nPRPHA subsidy ingest: {result['rows']:,} rows — {result['status']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
