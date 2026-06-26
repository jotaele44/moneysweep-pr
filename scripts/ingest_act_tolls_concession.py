"""
Ingest PR Highways & Transportation Authority (ACT) toll revenue and
Metropistas / Autopistas concession payments from operator-delivered files.
Distinct from the ACT *transition contracts* source.

Place exports from https://act.dtop.pr.gov/ (toll & Metropistas/Autopistas concession) into:
  data/raw/ACT_Tolls/

Output:
  data/staging/processed/pr_act_tolls.csv

Usage:
  python3 scripts/ingest_act_tolls_concession.py
  python3 scripts/ingest_act_tolls_concession.py --force
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from moneysweep.runtime.dropzone_ingest import ingest_dropzone
from scripts.config import PROJECT_ROOT

RAW_DIR_NAME = "data/raw/ACT_Tolls"
OUTPUT_PATH = "data/staging/processed/pr_act_tolls.csv"
KEY_FIELD = "facility"

OUTPUT_COLUMNS = [
    "facility",
    "operator_name",
    "period",
    "toll_revenue",
    "transactions",
    "concession_payment",
    "source_file",
]

COL_MAP = {
    "facility": ["facilidad", "facility", "autopista", "carretera", "via", "vía"],
    "operator_name": ["operador", "operator", "operator_name", "concesionario"],
    "period": ["periodo", "período", "period", "fecha", "ano", "año"],
    "toll_revenue": ["peajes", "ingresos", "toll_revenue", "recaudo", "revenue"],
    "transactions": ["transacciones", "transactions", "conteo", "trafico", "tráfico"],
    "concession_payment": [
        "pago",
        "concession_payment",
        "canon",
        "pago_concesion",
        "pago_concesión",
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
        source_name="ingest_act_tolls_concession",
        force=force,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="Re-ingest even if output exists")
    args = parser.parse_args()
    result = run(force=args.force)
    print(f"\nACT tolls ingest: {result['rows']:,} rows — {result['status']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
