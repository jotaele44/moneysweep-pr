"""
Ingest DDEC Act 60/20/22 tax-incentive decrees (export-services and
individual-investor grants) from operator-delivered files.

Place exports from https://www.ddec.pr.gov/ (Act 60/20/22 incentive decrees) into:
  data/raw/DDEC_Incentives/

Output:
  data/staging/processed/pr_ddec_incentives.csv

Usage:
  python3 scripts/ingest_ddec_incentives.py
  python3 scripts/ingest_ddec_incentives.py --force
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from contract_sweeper.runtime.dropzone_ingest import ingest_dropzone
from scripts.config import PROJECT_ROOT

RAW_DIR_NAME = "data/raw/DDEC_Incentives"
OUTPUT_PATH = "data/staging/processed/pr_ddec_incentives.csv"
KEY_FIELD = "beneficiary_name"

OUTPUT_COLUMNS = [
    "decree_number",
    "beneficiary_name",
    "act",
    "incentive_type",
    "tax_benefit",
    "grant_date",
    "expiration_date",
    "municipality",
    "employees_committed",
    "source_file",
]

COL_MAP = {
    "decree_number": ["decreto", "numero_decreto", "número_decreto", "decree_number", "case"],
    "beneficiary_name": [
        "beneficiario",
        "nombre",
        "beneficiary",
        "beneficiary_name",
        "concesionario",
    ],
    "act": ["ley", "act", "acto"],
    "incentive_type": ["tipo_incentivo", "incentivo", "incentive_type", "categoria", "categoría"],
    "tax_benefit": ["beneficio", "tax_benefit", "tasa", "exencion", "exención"],
    "grant_date": ["fecha_otorgamiento", "fecha", "grant_date", "fecha_efectividad"],
    "expiration_date": ["fecha_expiracion", "fecha_expiración", "vencimiento", "expiration_date"],
    "municipality": ["municipio", "municipality", "pueblo"],
    "employees_committed": [
        "empleos",
        "empleados",
        "employees",
        "employees_committed",
        "empleos_comprometidos",
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
        source_name="ingest_ddec_incentives",
        force=force,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="Re-ingest even if output exists")
    args = parser.parse_args()
    result = run(force=args.force)
    print(f"\nDDEC incentives ingest: {result['rows']:,} rows — {result['status']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
