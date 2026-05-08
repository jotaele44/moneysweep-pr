"""Run R3 source coverage and master-input audit."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from contract_sweeper.validation.source_coverage import run_audit


def main() -> int:
    parser = argparse.ArgumentParser(description="Run R3 source coverage + master-input audit")
    parser.add_argument("--root", default=".", help="Project root directory")
    args = parser.parse_args()

    result = run_audit(Path(args.root))
    print(f"r3_gate_passed: {result.get('r3_gate_passed')}")
    print(f"phase_7_8_blocked: {result.get('phase_7_8_blocked')}")
    print(f"r3_primary_collapse_cause: {result.get('r3_primary_collapse_cause')}")
    print(f"builder_present_input_count: {result.get('builder_present_input_count')}")
    print(f"builder_expected_input_count: {result.get('builder_expected_input_count')}")
    print(json.dumps(result, indent=2))
    print("wrote: data/exports/source_coverage_audit.csv")
    print("wrote: data/exports/source_field_completeness.csv")
    print("wrote: data/review_queue/source_backfill_queue.csv")
    print("wrote: data/exports/rebuild_status.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
