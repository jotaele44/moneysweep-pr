"""
Ingest aggregate TOLL revenue (ACT / AutoExpreso / Metropistas).

Income side of the highway network: what the public pays to use the toll roads.
Figures are aggregate/published (ACT audited financials, MSRB EMMA continuing
disclosures for the toll-revenue bonds, budgets) — never individual crossings.
Dropzone reader, not a scraper. Operator drops exports into data/manual/act_toll_revenue/.

Output: data/staging/processed/pr_act_toll_revenue.csv

Usage:
  python3 scripts/ingest_toll_revenue.py
  python3 scripts/ingest_toll_revenue.py --force
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts._revenue_common import run_revenue_ingest


def run(root=None):
    return run_revenue_ingest(
        logger_name="ingest_toll_revenue",
        drop_subdir="data/manual/act_toll_revenue",
        out_filename="pr_act_toll_revenue.csv",
        service_domain="toll",
        collecting_agency="AUTORIDAD DE CARRETERAS Y TRANSPORTACION",
        root=root,
    )


def main():
    parser = argparse.ArgumentParser(description="Ingest aggregate toll revenue")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    result = run_revenue_ingest(
        logger_name="ingest_toll_revenue",
        drop_subdir="data/manual/act_toll_revenue",
        out_filename="pr_act_toll_revenue.csv",
        service_domain="toll",
        collecting_agency="AUTORIDAD DE CARRETERAS Y TRANSPORTACION",
        force=args.force,
    )
    print(f"\nToll revenue ingestion complete: {result['rows']:,} rows")
    return 1 if result["errors"] and result["rows"] == 0 else 0


if __name__ == "__main__":
    sys.exit(main())
