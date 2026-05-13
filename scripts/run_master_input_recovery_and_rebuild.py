"""Run R4 master-input recovery and fail-closed rebuild."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from contract_sweeper.validation.master_input_recovery import run_recovery_and_rebuild


def main() -> int:
    parser = argparse.ArgumentParser(description="Run R4 master input recovery + rebuild")
    parser.add_argument("--root", default=".", help="Project root directory")
    parser.add_argument(
        "--allow-partial-rebuild",
        action="store_true",
        help="Allow rebuild attempt even if unresolved inputs remain (default: fail-closed)",
    )
    args = parser.parse_args()

    result = run_recovery_and_rebuild(
        Path(args.root),
        allow_partial_rebuild=args.allow_partial_rebuild,
    )
    print(f"r4_gate_passed: {result.get('r4_gate_passed')}")
    print(f"phase_7_8_blocked: {result.get('phase_7_8_blocked')}")
    print(f"expected_input_count: {result.get('expected_input_count')}")
    print(f"mapped_input_count: {result.get('mapped_input_count')}")
    print(f"missing_input_count: {result.get('missing_input_count')}")
    print(f"forbidden_candidate_count: {result.get('forbidden_candidate_count')}")
    if result.get("build_error"):
        print(f"build_error: {result['build_error']}")
    print(json.dumps(result, indent=2))
    print("wrote: data/exports/master_input_recovery_audit.csv")
    print("wrote: data/exports/master_input_recovery_audit.json")
    print("wrote: data/review_queue/master_input_recovery_blockers.csv")
    print("wrote: data/exports/rebuild_status.json")
    print("wrote: data/exports/r49_rebuild_audit.json")
    print("wrote: data/exports/r49_source_contribution_matrix.csv")
    print("wrote: data/exports/r49_deduplication_trace.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
