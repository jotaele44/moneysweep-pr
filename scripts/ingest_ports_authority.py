"""
Ingest PR Ports Authority (Autoridad de los Puertos) concession fees and leases
(e.g. the Aerostar / Luis Muñoz Marín airport lease) from operator-delivered files.

Place exports from https://www.prpa.pr.gov/ (Autoridad de los Puertos) into:
  data/raw/Ports/

Output:
  data/staging/processed/pr_ports_concessions.csv

Usage:
  python3 scripts/ingest_ports_authority.py
  python3 scripts/ingest_ports_authority.py --force
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from contract_sweeper.runtime.dropzone_ingest import ingest_dropzone
from scripts.config import PROJECT_ROOT

RAW_DIR_NAME = "data/raw/Ports"
OUTPUT_PATH = "data/staging/processed/pr_ports_concessions.csv"
KEY_FIELD = "counterparty_name"

OUTPUT_COLUMNS = [
    "agreement_id",
    "counterparty_name",
    "facility",
    "agreement_type",
    "annual_payment",
    "term_start",
    "term_end",
    "source_file",
]

COL_MAP = {
    "agreement_id": ["numero", "numero_acuerdo", "agreement_id", "contrato", "id"],
    "counterparty_name": [
        "concesionario",
        "arrendatario",
        "counterparty",
        "counterparty_name",
        "nombre",
        "operador",
    ],
    "facility": ["facilidad", "facility", "puerto", "aeropuerto", "instalacion", "instalación"],
    "agreement_type": [
        "tipo",
        "agreement_type",
        "tipo_acuerdo",
        "concesion",
        "concesión",
        "arrendamiento",
    ],
    "annual_payment": ["pago", "pago_anual", "annual_payment", "canon", "monto"],
    "term_start": ["inicio", "term_start", "vigencia_desde", "fecha_inicio"],
    "term_end": ["fin", "term_end", "vigencia_hasta", "fecha_fin"],
}


def run(root: Path | None = None, force: bool = False) -> dict:
    return ingest_dropzone(
        root=root or PROJECT_ROOT,
        raw_dir_name=RAW_DIR_NAME,
        output_path=OUTPUT_PATH,
        output_columns=OUTPUT_COLUMNS,
        col_map=COL_MAP,
        key_field=KEY_FIELD,
        source_name="ingest_ports_authority",
        force=force,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="Re-ingest even if output exists")
    args = parser.parse_args()
    result = run(force=args.force)
    print(f"\nPorts authority ingest: {result['rows']:,} rows — {result['status']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
