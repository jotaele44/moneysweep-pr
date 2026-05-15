"""Run R4.6 backfill execution plan generation."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from contract_sweeper.validation.backfill_execution_plan import run_plan


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate R4.6 backfill execution plan")
    parser.add_argument("--root", default=".", help="Project root directory")
    args = parser.parse_args()

    result = run_plan(Path(args.root))
    print(f"plan_row_count: {result.get('plan_row_count')}")
    print(f"phase_7_8_blocked: {result.get('phase_7_8_blocked')}")
    print(f"row_fabrication_policy: {result.get('row_fabrication_policy')}")
    print(json.dumps(result, indent=2))
    print("wrote: data/exports/backfill_execution_plan_r4_6.csv")
    print("wrote: data/exports/backfill_execution_plan_r4_6.md")
    print("wrote: data/exports/backfill_execution_plan_r4_6_status.json")
    print("wrote: data/exports/rebuild_status.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
