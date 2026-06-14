"""
Ingest aggregate UTILITY rate revenue (PRASA water/sewer + PREPA/LUMA power).

Income side of the utilities: aggregate rate revenue billed to ratepayers, from
audited financials, rate-case filings, and MSRB EMMA disclosures (PRASA and the
legacy PREPA revenue bonds are revenue-pledged, hence disclosed). Aggregate only,
never individual accounts. Dropzone reader.

Dropzones / outputs:
  data/manual/prasa_rate_revenue/ -> data/staging/processed/pr_prasa_rate_revenue.csv
  data/manual/prepa_rate_revenue/ -> data/staging/processed/pr_prepa_rate_revenue.csv

Usage:
  python3 scripts/ingest_utility_revenue.py
  python3 scripts/ingest_utility_revenue.py --force
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts._revenue_common import run_revenue_ingest

_UTILITIES = [
    dict(
        logger_name="ingest_prasa_rate_revenue",
        drop_subdir="data/manual/prasa_rate_revenue",
        out_filename="pr_prasa_rate_revenue.csv",
        service_domain="utility",
        collecting_agency="AUTORIDAD DE ACUEDUCTOS Y ALCANTARILLADOS",
    ),
    dict(
        logger_name="ingest_prepa_rate_revenue",
        drop_subdir="data/manual/prepa_rate_revenue",
        out_filename="pr_prepa_rate_revenue.csv",
        service_domain="utility",
        collecting_agency="AUTORIDAD DE ENERGIA ELECTRICA",
    ),
]


def run(root=None, force=False):
    results = [run_revenue_ingest(root=root, force=force, **kw) for kw in _UTILITIES]
    return {
        "rows": sum(r["rows"] for r in results),
        "paths": [r["path"] for r in results],
        "errors": [e for r in results for e in r["errors"]],
    }


def main():
    parser = argparse.ArgumentParser(description="Ingest aggregate utility rate revenue")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    result = run(force=args.force)
    print(f"\nUtility rate revenue ingestion complete: {result['rows']:,} rows")
    return 1 if result["errors"] and result["rows"] == 0 else 0


if __name__ == "__main__":
    sys.exit(main())
