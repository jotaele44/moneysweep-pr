"""
Ingest DTOP / ACT permanent road construction & maintenance contracts.

The "where the money goes" / outflow counterpart to toll revenue: rolling road
construction and maintenance awards beyond the one-time 2020 transition snapshot.
Sourced from the OCPR contract registry (consultacontratos.ocpr.gov.pr, ACT agency
code 032) and the ACT/DTOP transparency page. Dropzone reader.
Operator drops exports into data/manual/dtop_road_contracts/.

Output: data/staging/processed/pr_dtop_road_contracts.csv

Usage:
  python3 scripts/ingest_dtop_road_contracts.py [--force]
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts._contract_dropzone import run_contract_ingest

_KW = dict(
    logger_name="ingest_dtop_road_contracts",
    drop_subdir="data/manual/dtop_road_contracts",
    out_filename="pr_dtop_road_contracts.csv",
    agency="DEPARTAMENTO DE TRANSPORTACION Y OBRAS PUBLICAS",
)


def run(root=None):
    return run_contract_ingest(root=root, **_KW)


def main():
    parser = argparse.ArgumentParser(description="Ingest DTOP/ACT road contracts")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    result = run_contract_ingest(force=args.force, **_KW)
    print(f"\nDTOP road contracts ingestion complete: {result['rows']:,} records")
    return 1 if result["errors"] and result["rows"] == 0 else 0


if __name__ == "__main__":
    sys.exit(main())
