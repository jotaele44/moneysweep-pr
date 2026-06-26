"""Run R0 production-status gate and stamp existing outputs."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from moneysweep.validation.production_status import run_gate


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate and stamp production status for current outputs"
    )
    parser.add_argument("--root", default=".", help="Project root directory")
    args = parser.parse_args()

    result = run_gate(Path(args.root))
    print(f"production_status: {result['production_status']}")
    print(f"blocker_count: {result['blocker_count']}")
    print(json.dumps(result.get("metrics", {}), indent=2))
    print("wrote: data/exports/production_status.json")
    print("wrote: data/review_queue/production_blockers.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
