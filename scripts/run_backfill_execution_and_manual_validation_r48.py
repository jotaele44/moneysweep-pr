"""Run R4.8 controlled backfill execution and manual import validation."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from contract_sweeper.pipeline.backfill_execution import run_backfill_execution


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Execute R4.8 controlled backfill plan and manual import validation"
    )
    parser.add_argument("--root", default=".", help="Project root directory")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Plan-only mode. This is the default when --execute-downloads is not provided.",
    )
    parser.add_argument(
        "--execute-downloads",
        action="store_true",
        help="Explicit opt-in to execute real producer commands.",
    )
    parser.add_argument(
        "--skip-manual-slot-validation",
        action="store_true",
        help="Skip validation of manual import slots.",
    )
    args = parser.parse_args()

    dry_run = True if not args.execute_downloads else bool(args.dry_run)

    result = run_backfill_execution(
        Path(args.root),
        dry_run=dry_run,
        execute_downloads=bool(args.execute_downloads),
        validate_manual_slots=not bool(args.skip_manual_slot_validation),
    )

    print(f"r4_8_gate_passed: {result.get('r4_8_gate_passed')}")
    print(f"phase_7_8_blocked: {result.get('phase_7_8_blocked')}")
    print(f"r4_8_total_sources: {result.get('r4_8_total_sources')}")
    print(f"r4_8_validated_sources: {result.get('r4_8_validated_sources')}")
    print(f"r4_8_failed_sources: {result.get('r4_8_failed_sources')}")
    print(f"r4_8_downloads_executed: {result.get('r4_8_downloads_executed')}")
    print(f"row_fabrication_policy: {result.get('row_fabrication_policy')}")
    print(json.dumps(result, indent=2))
    print("wrote: data/exports/backfill_execution_results_r4_8.csv")
    print("wrote: data/exports/manual_import_validation_r4_8.csv")
    print("wrote: data/review_queue/backfill_execution_blockers_r4_8.csv")
    print("wrote: data/review_queue/manual_import_validation_failures_r4_8.csv")
    print("wrote: data/exports/backfill_execution_status_r4_8.json")
    print("wrote: data/exports/rebuild_status.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
