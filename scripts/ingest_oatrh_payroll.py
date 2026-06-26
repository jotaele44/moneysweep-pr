"""
Ingest PR central-government payroll / salaries (OATRH 'Nómina') from
operator-delivered files.

Place exports from https://www.oatrh.pr.gov/ (central government payroll / Nómina) into:
  data/raw/OATRH_Payroll/

Output:
  data/staging/processed/pr_govt_payroll.csv

Usage:
  python3 scripts/ingest_oatrh_payroll.py
  python3 scripts/ingest_oatrh_payroll.py --force
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from moneysweep.runtime.dropzone_ingest import ingest_dropzone
from scripts.config import PROJECT_ROOT

RAW_DIR_NAME = "data/raw/OATRH_Payroll"
OUTPUT_PATH = "data/staging/processed/pr_govt_payroll.csv"
KEY_FIELD = "employee_name"

OUTPUT_COLUMNS = [
    "employee_name",
    "agency",
    "position",
    "annual_salary",
    "fiscal_year",
    "employment_type",
    "source_file",
]

COL_MAP = {
    "employee_name": ["empleado", "nombre", "employee", "employee_name", "servidor"],
    "agency": ["agencia", "agency", "entidad", "departamento"],
    "position": [
        "puesto",
        "position",
        "cargo",
        "clasificacion",
        "clasificación",
        "titulo",
        "título",
    ],
    "annual_salary": [
        "salario",
        "sueldo",
        "annual_salary",
        "salary",
        "salario_anual",
        "remuneracion",
        "remuneración",
    ],
    "fiscal_year": ["ano_fiscal", "año_fiscal", "fiscal_year", "year", "ano", "año"],
    "employment_type": [
        "tipo",
        "employment_type",
        "tipo_nombramiento",
        "status",
        "categoria",
        "categoría",
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
        source_name="ingest_oatrh_payroll",
        force=force,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="Re-ingest even if output exists")
    args = parser.parse_args()
    result = run(force=args.force)
    print(f"\nOATRH payroll ingest: {result['rows']:,} rows — {result['status']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
