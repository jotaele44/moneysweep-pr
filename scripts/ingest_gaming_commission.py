"""
Ingest PR Gaming Commission casino / slot-machine licensing and gaming-tax
revenue from operator-delivered files.

Place exports from https://www.jcapr.pr.gov/ (Gaming Commission) into:
  data/raw/Gaming/

Output:
  data/staging/processed/pr_gaming.csv

Usage:
  python3 scripts/ingest_gaming_commission.py
  python3 scripts/ingest_gaming_commission.py --force
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from moneysweep.runtime.dropzone_ingest import ingest_dropzone
from scripts.config import PROJECT_ROOT

RAW_DIR_NAME = "data/raw/Gaming"
OUTPUT_PATH = "data/staging/processed/pr_gaming.csv"
KEY_FIELD = "licensee_name"

OUTPUT_COLUMNS = [
    "license_number",
    "licensee_name",
    "license_type",
    "location",
    "gaming_revenue",
    "tax_paid",
    "fiscal_year",
    "machine_count",
    "source_file",
]

COL_MAP = {
    "license_number": ["licencia", "numero_licencia", "número_licencia", "license_number"],
    "licensee_name": ["concesionario", "operador", "licensee", "licensee_name", "nombre", "casino"],
    "license_type": ["tipo", "tipo_licencia", "license_type", "categoria", "categoría"],
    "location": ["ubicacion", "ubicación", "location", "municipio", "localidad"],
    "gaming_revenue": ["ingresos", "revenue", "gaming_revenue", "ingresos_juego"],
    "tax_paid": ["contribucion", "contribución", "tax", "tax_paid", "impuesto"],
    "fiscal_year": ["ano_fiscal", "año_fiscal", "fiscal_year", "year"],
    "machine_count": ["maquinas", "máquinas", "machines", "machine_count", "slots"],
}


def run(root: Path | None = None, force: bool = False) -> dict:
    return ingest_dropzone(
        root=root or PROJECT_ROOT,
        raw_dir_name=RAW_DIR_NAME,
        output_path=OUTPUT_PATH,
        output_columns=OUTPUT_COLUMNS,
        col_map=COL_MAP,
        key_field=KEY_FIELD,
        source_name="ingest_gaming_commission",
        force=force,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="Re-ingest even if output exists")
    args = parser.parse_args()
    result = run(force=args.force)
    print(f"\nGaming commission ingest: {result['rows']:,} rows — {result['status']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
