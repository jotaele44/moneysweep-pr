"""
Ingest the PR Comptroller (OCPR) contract registry from operator-delivered files.

Every contract granted by a PR government entity must be registered with the
Oficina del Contralor de Puerto Rico (OCPR) at consultacontratos.ocpr.gov.pr.
This is the canonical record of *all* PR government contracts — distinct from the
existing ``oficina_contralor`` source, which carries only OCPR *audit reports*.
The public registry is an interactive search surface with no machine API, so the
ingestion path is operator-delivered CSV/Excel exports until a dedicated scraper
is built.

Place exports from https://consultacontratos.ocpr.gov.pr/ into:
  data/raw/OCPR_Contracts/

Output:
  data/staging/processed/pr_ocpr_contracts.csv

Usage:
  python3 scripts/ingest_ocpr_contracts.py
  python3 scripts/ingest_ocpr_contracts.py --force
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from moneysweep.runtime.dropzone_ingest import ingest_dropzone
from scripts.config import PROJECT_ROOT

RAW_DIR_NAME = "data/raw/OCPR_Contracts"
OUTPUT_PATH = "data/staging/processed/pr_ocpr_contracts.csv"
KEY_FIELD = "contract_number"

OUTPUT_COLUMNS = [
    "contract_number",
    "contractor_name",
    "contractor_id",
    "agency",
    "contract_amount",
    "start_date",
    "end_date",
    "service_description",
    "contract_type",
    "status",
    "source_file",
]

COL_MAP = {
    "contract_number": [
        "numero_contrato",
        "número_contrato",
        "num_contrato",
        "contract_number",
        "contrato",
    ],
    "contractor_name": [
        "nombre_contratista",
        "contratista",
        "suplidor",
        "contractor_name",
        "nombre",
    ],
    "contractor_id": ["id_contratista", "registro_comerciante", "contractor_id", "numero_registro"],
    "agency": ["entidad", "agencia", "entidad_gubernamental", "agency", "municipio"],
    "contract_amount": [
        "cuantia",
        "cuantía",
        "monto",
        "cantidad",
        "amount",
        "contract_amount",
        "valor",
    ],
    "start_date": [
        "fecha_inicio",
        "fecha_otorgamiento",
        "fecha_efectividad",
        "start_date",
        "vigencia_desde",
    ],
    "end_date": ["fecha_vencimiento", "fecha_fin", "end_date", "vigencia_hasta"],
    "service_description": [
        "descripcion",
        "descripción",
        "servicio",
        "objeto",
        "service_description",
        "proposito",
    ],
    "contract_type": ["tipo_contrato", "tipo", "clasificacion", "clasificación", "contract_type"],
    "status": ["estatus", "estado", "status", "vigente"],
}


def run(root: Path | None = None, force: bool = False) -> dict:
    return ingest_dropzone(
        root=root or PROJECT_ROOT,
        raw_dir_name=RAW_DIR_NAME,
        output_path=OUTPUT_PATH,
        output_columns=OUTPUT_COLUMNS,
        col_map=COL_MAP,
        key_field=KEY_FIELD,
        source_name="ingest_ocpr_contracts",
        force=force,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="Re-ingest even if output exists")
    args = parser.parse_args()
    result = run(force=args.force)
    print(f"\nOCPR contracts ingest: {result['rows']:,} rows — {result['status']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
