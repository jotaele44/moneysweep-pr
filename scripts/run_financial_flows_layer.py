"""Run Phase 6 financial flow master builder."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from contract_sweeper.flows import run_financial_flows


def main() -> int:
    parser = argparse.ArgumentParser(description="Run financial flows master builder")
    parser.add_argument("--input", help="Optional execution_chain_master.csv path")
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parent.parent
    artifacts = run_financial_flows(
        project_root=project_root,
        input_path=Path(args.input).resolve() if args.input else None,
    )

    print(f"financial_flows_master.parquet: {artifacts.financial_flows_master_parquet}")
    print(f"financial_flows_master.csv: {artifacts.financial_flows_master_csv}")
    print(f"summary: {artifacts.summary_json}")
    print(f"rows: {artifacts.summary.get('rows_total', 0)}")
    print(f"total_amount: {artifacts.summary.get('total_amount', 0)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
