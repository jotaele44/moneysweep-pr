"""
Ingest CRIM (Centro de Recaudación de Ingresos Municipales) property-tax
assessment and collection records from operator-delivered files.

Place exports from https://www.crimpr.net/ (municipal property tax) into:
  data/raw/CRIM/

Output:
  data/staging/processed/pr_crim_property_tax.csv

Usage:
  python3 scripts/ingest_crim_property_tax.py
  python3 scripts/ingest_crim_property_tax.py --force
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from moneysweep.runtime.dropzone_ingest import ingest_dropzone
from scripts.config import PROJECT_ROOT

RAW_DIR_NAME = "data/raw/CRIM"
OUTPUT_PATH = "data/staging/processed/pr_crim_property_tax.csv"
KEY_FIELD = "cadastre_number"

OUTPUT_COLUMNS = [
    "cadastre_number",
    "owner_name",
    "municipality",
    "assessed_value",
    "tax_amount",
    "fiscal_year",
    "property_type",
    "exoneration",
    "source_file",
]

COL_MAP = {
    "cadastre_number": [
        "catastro",
        "numero_catastro",
        "número_catastro",
        "cadastre",
        "cadastre_number",
        "clave",
    ],
    "owner_name": ["dueno", "dueño", "propietario", "owner", "owner_name", "contribuyente"],
    "municipality": ["municipio", "municipality", "pueblo"],
    "assessed_value": ["valor_tasado", "tasacion", "tasación", "assessed_value", "valor"],
    "tax_amount": ["contribucion", "contribución", "tax_amount", "impuesto", "monto"],
    "fiscal_year": ["ano_fiscal", "año_fiscal", "fiscal_year", "year"],
    "property_type": ["tipo_propiedad", "clasificacion", "clasificación", "property_type", "tipo"],
    "exoneration": ["exoneracion", "exoneración", "exencion", "exención", "exoneration"],
}


def run(root: Path | None = None, force: bool = False) -> dict:
    return ingest_dropzone(
        root=root or PROJECT_ROOT,
        raw_dir_name=RAW_DIR_NAME,
        output_path=OUTPUT_PATH,
        output_columns=OUTPUT_COLUMNS,
        col_map=COL_MAP,
        key_field=KEY_FIELD,
        source_name="ingest_crim_property_tax",
        force=force,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="Re-ingest even if output exists")
    args = parser.parse_args()
    result = run(force=args.force)
    print(f"\nCRIM property tax ingest: {result['rows']:,} rows — {result['status']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
