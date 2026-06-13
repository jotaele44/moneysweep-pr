"""
Ingest aggregate TRANSIT fare revenue (AMA buses / Tren Urbano-ATI).

Income side of public transit: aggregate farebox revenue from audited financials
and budgets. Not individual rider transactions. Dropzone reader.
Operator drops exports into data/manual/transit_fare_revenue/.

Output: data/staging/processed/pr_transit_fare_revenue.csv

Usage:
  python3 scripts/ingest_transit_fare_revenue.py
  python3 scripts/ingest_transit_fare_revenue.py --force
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts._revenue_common import run_revenue_ingest

_KW = dict(
    logger_name="ingest_transit_fare_revenue",
    drop_subdir="data/manual/transit_fare_revenue",
    out_filename="pr_transit_fare_revenue.csv",
    service_domain="transit",
    collecting_agency="AUTORIDAD METROPOLITANA DE AUTOBUSES",
)


def run(root=None):
    return run_revenue_ingest(root=root, **_KW)


def main():
    parser = argparse.ArgumentParser(description="Ingest aggregate transit fare revenue")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    result = run_revenue_ingest(force=args.force, **_KW)
    print(f"\nTransit fare revenue ingestion complete: {result['rows']:,} rows")
    return 1 if result["errors"] and result["rows"] == 0 else 0


if __name__ == "__main__":
    sys.exit(main())
