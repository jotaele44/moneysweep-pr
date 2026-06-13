"""
Extract bond-pledged infrastructure REVENUE from MSRB EMMA continuing disclosures.

Toll, water, and power revenue in Puerto Rico is pledged to revenue bonds, so the
issuers must file continuing-disclosure reports on MSRB EMMA — making aggregate
revenue figures public. EMMA is `authentication: none`, so this is the one automatable
revenue spine and a cross-check against the operator's manual dropzone figures.

EMMA disclosure documents are semi-structured PDFs; robust extraction is best-effort
(Tranche 4). This module reads any operator-staged EMMA disclosure CSVs (already
tabulated) from the dropzone and normalizes them into the shared revenue schema; full
PDF parsing is a follow-up. Graceful when no input is present.

Dropzone: data/manual/emma_revenue/
Output:   data/staging/processed/pr_emma_revenue_disclosures.csv

Usage:
  python3 scripts/extract_emma_revenue.py [--force]
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts._revenue_common import run_revenue_ingest


def run(root=None, force=False):
    # Reuse the revenue dropzone normalizer; EMMA rows carry their own collecting
    # agency per filing, so the default agency is only a fallback.
    return run_revenue_ingest(
        logger_name="extract_emma_revenue",
        drop_subdir="data/manual/emma_revenue",
        out_filename="pr_emma_revenue_disclosures.csv",
        service_domain="toll",
        collecting_agency="EMMA CONTINUING DISCLOSURE",
        root=root,
        force=force,
    )


def main():
    parser = argparse.ArgumentParser(description="Extract EMMA bond-pledged revenue")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    result = run(force=args.force)
    print(f"\nEMMA revenue extraction complete: {result['rows']:,} rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
