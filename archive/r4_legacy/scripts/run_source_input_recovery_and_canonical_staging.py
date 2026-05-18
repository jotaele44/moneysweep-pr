"""Run R4.5 source input recovery + canonical staging."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from contract_sweeper.validation.source_input_recovery import run_recovery


def main() -> int:
    parser = argparse.ArgumentParser(description="Run R4.5 source input recovery and canonical staging")
    parser.add_argument("--root", default=".", help="Project root directory")
    args = parser.parse_args()

    result = run_recovery(Path(args.root))
    print(f"r4_5_gate_passed: {result.get('r4_5_gate_passed')}")
    print(f"phase_7_8_blocked: {result.get('phase_7_8_blocked')}")
    print(f"expected_input_count: {result.get('expected_input_count')}")
    print(f"recovered_input_count: {result.get('recovered_input_count')}")
    print(f"manual_queue_count: {result.get('manual_queue_count')}")
    print(f"rejected_artifact_candidate_count: {result.get('rejected_artifact_candidate_count')}")
    print(json.dumps(result, indent=2))
    print("wrote: data/exports/source_input_recovery_audit.csv")
    print("wrote: data/exports/source_input_recovery_status.json")
    print("wrote: data/review_queue/manual_source_download_queue.csv")
    print("wrote: data/exports/rebuild_status.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
