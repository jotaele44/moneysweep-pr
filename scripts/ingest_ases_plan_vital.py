"""
Ingest ASES (Administración de Seguros de Salud) Plan Vital Medicaid
managed-care contracts and MCO capitation from operator-delivered files. This is
the PR territorial program spend, distinct from the federal FMAP match.

Place exports from https://www.asespr.org/ (Plan Vital managed-care contracts) into:
  data/raw/ASES/

Output:
  data/staging/processed/pr_ases_contracts.csv

Usage:
  python3 scripts/ingest_ases_plan_vital.py
  python3 scripts/ingest_ases_plan_vital.py --force
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from moneysweep.runtime.dropzone_ingest import ingest_dropzone
from scripts.config import PROJECT_ROOT

RAW_DIR_NAME = "data/raw/ASES"
OUTPUT_PATH = "data/staging/processed/pr_ases_contracts.csv"
KEY_FIELD = "mco_name"

OUTPUT_COLUMNS = [
    "contract_number",
    "mco_name",
    "contract_amount",
    "capitation_pmpm",
    "region",
    "enrollment",
    "contract_period",
    "source_file",
]

COL_MAP = {
    "contract_number": ["numero_contrato", "número_contrato", "contract_number", "contrato"],
    "mco_name": ["aseguradora", "mco", "plan", "mco_name", "nombre", "contratista"],
    "contract_amount": ["monto", "cuantia", "cuantía", "contract_amount", "amount", "valor"],
    "capitation_pmpm": ["capita", "cápita", "pmpm", "capitation", "capitation_pmpm"],
    "region": ["region", "región", "area", "área"],
    "enrollment": ["matricula", "matrícula", "enrollment", "beneficiarios", "afiliados"],
    "contract_period": ["periodo", "período", "vigencia", "contract_period"],
}


def run(root: Path | None = None, force: bool = False) -> dict:
    return ingest_dropzone(
        root=root or PROJECT_ROOT,
        raw_dir_name=RAW_DIR_NAME,
        output_path=OUTPUT_PATH,
        output_columns=OUTPUT_COLUMNS,
        col_map=COL_MAP,
        key_field=KEY_FIELD,
        source_name="ingest_ases_plan_vital",
        force=force,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="Re-ingest even if output exists")
    args = parser.parse_args()
    result = run(force=args.force)
    print(f"\nASES Plan Vital ingest: {result['rows']:,} rows — {result['status']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
