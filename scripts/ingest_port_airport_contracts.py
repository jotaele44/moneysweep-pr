"""
Ingest Ports & Airports Authority contracts (PR Ports Authority / Aerostar-SJU).

Outflow counterpart to port/airport fee revenue. Sourced from the Ports Authority
transparency page, OCPR registry, and the already-acquired AAA completed-projects
records (see scripts/parse_aaa_ports_pdf.py). Dropzone reader.
Operator drops exports into data/manual/ports_airports_contracts/.

Output: data/staging/processed/pr_ports_airports_contracts.csv

Usage:
  python3 scripts/ingest_port_airport_contracts.py [--force]
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts._contract_dropzone import run_contract_ingest

_KW = dict(
    logger_name="ingest_port_airport_contracts",
    drop_subdir="data/manual/ports_airports_contracts",
    out_filename="pr_ports_airports_contracts.csv",
    agency="AUTORIDAD DE LOS PUERTOS",
)


def run(root=None):
    return run_contract_ingest(root=root, **_KW)


def main():
    parser = argparse.ArgumentParser(description="Ingest ports/airports contracts")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    result = run_contract_ingest(force=args.force, **_KW)
    print(f"\nPorts/airports contracts ingestion complete: {result['rows']:,} records")
    return 1 if result["errors"] and result["rows"] == 0 else 0


if __name__ == "__main__":
    sys.exit(main())
