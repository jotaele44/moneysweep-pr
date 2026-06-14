"""
Ingest Banco de Desarrollo Económico (Economic Development Bank) territorial
business loans from operator-delivered files. Distinct from federal SBA loans.

Place exports from https://www.bde.pr.gov/ (Banco de Desarrollo Económico) into:
  data/raw/BDE/

Output:
  data/staging/processed/pr_bde_loans.csv

Usage:
  python3 scripts/ingest_bde_loans.py
  python3 scripts/ingest_bde_loans.py --force
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from contract_sweeper.runtime.dropzone_ingest import ingest_dropzone
from scripts.config import PROJECT_ROOT

RAW_DIR_NAME = "data/raw/BDE"
OUTPUT_PATH = "data/staging/processed/pr_bde_loans.csv"
KEY_FIELD = "borrower_name"

OUTPUT_COLUMNS = [
    "loan_number",
    "borrower_name",
    "loan_amount",
    "loan_type",
    "sector",
    "municipality",
    "approval_date",
    "status",
    "source_file",
]

COL_MAP = {
    "loan_number": ["numero_prestamo", "número_préstamo", "loan_number", "prestamo", "préstamo"],
    "borrower_name": ["prestatario", "cliente", "borrower", "borrower_name", "nombre", "negocio"],
    "loan_amount": ["monto", "cantidad", "loan_amount", "amount", "cuantia", "cuantía"],
    "loan_type": ["tipo_prestamo", "tipo_préstamo", "loan_type", "tipo", "programa"],
    "sector": ["sector", "industria", "actividad"],
    "municipality": ["municipio", "municipality", "pueblo"],
    "approval_date": ["fecha_aprobacion", "fecha_aprobación", "approval_date", "fecha"],
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
        source_name="ingest_bde_loans",
        force=force,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="Re-ingest even if output exists")
    args = parser.parse_args()
    result = run(force=args.force)
    print(f"\nBDE loans ingest: {result['rows']:,} rows — {result['status']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
