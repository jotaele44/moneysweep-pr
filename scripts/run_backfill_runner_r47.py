"""Run R4.7 backfill runner/import-slot plan generation."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from contract_sweeper.pipeline.backfill_runner import generate_backfill_runner_plan


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate R4.7 backfill runner and import slots")
    parser.add_argument("--root", default=".", help="Project root directory")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Emit/print planned commands only (default behavior).",
    )
    parser.add_argument(
        "--execute-downloads",
        action="store_true",
        help="Enable real command templates (explicit opt-in required).",
    )
    args = parser.parse_args()

    # Dry-run first by default even if flag omitted.
    dry_run = True if not args.execute_downloads else bool(args.dry_run)

    result = generate_backfill_runner_plan(
        Path(args.root),
        dry_run=dry_run,
        execute_downloads=bool(args.execute_downloads),
    )

    counts = result.get("counts", {})
    print(f"r4_7_gate_passed: {result.get('r4_7_gate_passed')}")
    print(f"phase_7_8_blocked: {result.get('phase_7_8_blocked')}")
    print(f"r4_7_phase_type: {result.get('r4_7_phase_type')}")
    print(f"r4_7_data_recovery_completed: {result.get('r4_7_data_recovery_completed')}")
    print(f"r4_7_downloads_executed: {result.get('r4_7_downloads_executed')}")
    print(f"r4_7_rows_ingested: {result.get('r4_7_rows_ingested')}")
    print(f"r4_7_production_inputs_staged: {result.get('r4_7_production_inputs_staged')}")
    print(f"total_sources: {counts.get('total_sources')}")
    print(f"automated_sources: {counts.get('automated_sources')}")
    print(result.get("automated_source_count_definition"))
    print(f"manual_sources: {counts.get('manual_sources')}")
    print(f"blocked_sources: {counts.get('blocked_sources')}")
    print(f"execute_downloads_default: {result.get('execute_downloads_default')}")
    print(json.dumps(result, indent=2))
    print("wrote: data/exports/backfill_runner_plan_r4_7.json")
    print("wrote: data/exports/backfill_runner_manifest_r4_7.csv")
    print("wrote: data/exports/import_slots_r4_7.csv")
    print("wrote: data/review_queue/backfill_runner_blockers.csv")
    print("wrote: data/review_queue/manual_import_slots_required.csv")
    print("wrote: data/exports/rebuild_status.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
