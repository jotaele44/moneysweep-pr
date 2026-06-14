"""
Ingest aggregate PORT & AIRPORT fee revenue (PR Ports Authority / Aerostar-SJU).

Income side of maritime/air infrastructure: aggregate wharfage, landing, and
concession fees from audited financials and EMMA disclosures. Dropzone reader.
Operator drops exports into data/manual/ports_airports_revenue/.

Output: data/staging/processed/pr_ports_airports_revenue.csv

Usage:
  python3 scripts/ingest_port_airport_revenue.py
  python3 scripts/ingest_port_airport_revenue.py --force
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts._revenue_common import run_revenue_ingest

_KW = dict(
    logger_name="ingest_port_airport_revenue",
    drop_subdir="data/manual/ports_airports_revenue",
    out_filename="pr_ports_airports_revenue.csv",
    service_domain="port",
    collecting_agency="AUTORIDAD DE LOS PUERTOS",
)


def run(root=None):
    return run_revenue_ingest(root=root, **_KW)


def main():
    parser = argparse.ArgumentParser(description="Ingest aggregate port/airport fee revenue")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    result = run_revenue_ingest(force=args.force, **_KW)
    print(f"\nPort/airport revenue ingestion complete: {result['rows']:,} rows")
    return 1 if result["errors"] and result["rows"] == 0 else 0


if __name__ == "__main__":
    sys.exit(main())
