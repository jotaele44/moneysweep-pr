"""
Ingest OGPe (Oficina de Gerencia de Permisos) construction-permit fees and
green-energy incentives from operator-delivered files.

Place exports from https://www.ogpe.pr.gov/ (construction permits & incentives) into:
  data/raw/OGPe/

Output:
  data/staging/processed/pr_ogpe_permits.csv

Usage:
  python3 scripts/ingest_ogpe_permits.py
  python3 scripts/ingest_ogpe_permits.py --force
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from contract_sweeper.runtime.dropzone_ingest import ingest_dropzone
from scripts.config import PROJECT_ROOT

RAW_DIR_NAME = "data/raw/OGPe"
OUTPUT_PATH = "data/staging/processed/pr_ogpe_permits.csv"
KEY_FIELD = "permit_number"

OUTPUT_COLUMNS = [
    "permit_number",
    "applicant_name",
    "permit_type",
    "municipality",
    "project_value",
    "fee_paid",
    "issue_date",
    "status",
    "source_file",
]

COL_MAP = {
    "permit_number": ["numero_permiso", "número_permiso", "permit_number", "caso", "permiso"],
    "applicant_name": ["solicitante", "applicant", "applicant_name", "proponente", "nombre"],
    "permit_type": ["tipo_permiso", "tipo", "permit_type", "categoria", "categoría"],
    "municipality": ["municipio", "municipality", "pueblo"],
    "project_value": [
        "valor",
        "valor_proyecto",
        "project_value",
        "costo",
        "inversion",
        "inversión",
    ],
    "fee_paid": ["derechos", "fee", "fee_paid", "cargo", "arancel"],
    "issue_date": ["fecha_emision", "fecha_emisión", "issue_date", "fecha"],
    "status": ["estatus", "estado", "status"],
}


def run(root: Path | None = None, force: bool = False) -> dict:
    return ingest_dropzone(
        root=root or PROJECT_ROOT,
        raw_dir_name=RAW_DIR_NAME,
        output_path=OUTPUT_PATH,
        output_columns=OUTPUT_COLUMNS,
        col_map=COL_MAP,
        key_field=KEY_FIELD,
        source_name="ingest_ogpe_permits",
        force=force,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="Re-ingest even if output exists")
    args = parser.parse_args()
    result = run(force=args.force)
    print(f"\nOGPe permits ingest: {result['rows']:,} rows — {result['status']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
