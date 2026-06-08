#!/usr/bin/env python3
"""CLI for the Contract-Sweeper politics / public-finance intake lane.

Reads the PR-intake router's ``contract_sweeper_derivatives.csv`` and writes the
normalized finance tables + review queues. Counterpart to
``scripts/build_spiderweb_spatial_lane.py``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from readiness.contract_sweeper_finance_lane import (  # noqa: E402
    ContractSweeperFinanceLaneError,
    build_contract_sweeper_finance_lane,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input", required=True, help="Directory containing contract_sweeper_derivatives.csv"
    )
    parser.add_argument(
        "--out",
        default=None,
        help="Output directory for normalized lane artifacts; default: --input",
    )
    args = parser.parse_args(argv)
    try:
        report = build_contract_sweeper_finance_lane(args.input, args.out)
    except ContractSweeperFinanceLaneError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["zero_loss_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
