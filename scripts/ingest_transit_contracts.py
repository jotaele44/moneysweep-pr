"""
Ingest transit operating contracts (AMA buses / Tren Urbano-ATI).

Outflow counterpart to transit fare revenue: bus and urban-rail O&M / operator
contracts (e.g. the private operator of Tren Urbano). Sourced from the OCPR registry
and agency transparency pages. Dropzone reader.
Operator drops exports into data/manual/transit_contracts/.

Output: data/staging/processed/pr_transit_contracts.csv

Usage:
  python3 scripts/ingest_transit_contracts.py [--force]
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts._contract_dropzone import run_contract_ingest

_KW = dict(
    logger_name="ingest_transit_contracts",
    drop_subdir="data/manual/transit_contracts",
    out_filename="pr_transit_contracts.csv",
    agency="AUTORIDAD METROPOLITANA DE AUTOBUSES",
)


def run(root=None):
    return run_contract_ingest(root=root, **_KW)


def main():
    parser = argparse.ArgumentParser(description="Ingest transit operating contracts")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    result = run_contract_ingest(force=args.force, **_KW)
    print(f"\nTransit contracts ingestion complete: {result['rows']:,} records")
    return 1 if result["errors"] and result["rows"] == 0 else 0


if __name__ == "__main__":
    sys.exit(main())
