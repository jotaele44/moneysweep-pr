"""Run R4.8 controlled backfill execution and manual import validation."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from contract_sweeper.pipeline.controlled_backfill import run_controlled_backfill


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run controlled backfill plan and manual import validation for R4.8"
    )
    parser.add_argument("--root", default=".", help="Project root directory")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Plan-only mode (default when --execute-downloads is not passed).",
    )
    parser.add_argument(
        "--execute-downloads",
        action="store_true",
        help="Explicit opt-in to run real automated download commands.",
    )
    args = parser.parse_args()

    dry_run = True if not args.execute_downloads else bool(args.dry_run)

    result = run_controlled_backfill(
        Path(args.root),
        dry_run=dry_run,
        execute_downloads=bool(args.execute_downloads),
    )

    print(f"r4_8_gate_passed: {result.get('r4_8_gate_passed')}")
    print(f"phase_7_8_blocked: {result.get('phase_7_8_blocked')}")
    print(f"r4_8_total_sources: {result.get('r4_8_total_sources')}")
    print(f"r4_8_dry_run_ready_count: {result.get('r4_8_dry_run_ready_count')}")
    print(f"r4_8_executable_with_credentials_count: {result.get('r4_8_executable_with_credentials_count')}")
    print(f"r4_8_missing_credentials_count: {result.get('r4_8_missing_credentials_count')}")
    print(f"r4_8_manual_import_required_count: {result.get('r4_8_manual_import_required_count')}")
    print(f"r4_8_missing_schema_count: {result.get('r4_8_missing_schema_count')}")
    print(f"r4_8_blocked_count: {result.get('r4_8_blocked_count')}")
    print(f"r4_8_downloads_executed: {result.get('r4_8_downloads_executed')}")
    print(f"r4_8_rows_ingested: {result.get('r4_8_rows_ingested')}")
    print(f"r4_8_production_inputs_staged: {result.get('r4_8_production_inputs_staged')}")
    print(f"r4_8_source_manifests_written: {result.get('r4_8_source_manifests_written')}")
    print(f"row_fabrication_policy: {result.get('row_fabrication_policy')}")
    print(json.dumps(result, indent=2))
    print("wrote: data/exports/controlled_backfill_plan_r4_8.json")
    print("wrote: data/exports/controlled_backfill_manifest_r4_8.csv")
    print("wrote: data/exports/manual_import_validation_r4_8.csv")
    print("wrote: data/exports/source_manifest_inventory_r4_8.csv")
    print("wrote: data/review_queue/controlled_backfill_blockers.csv")
    print("wrote: data/review_queue/manual_import_validation_errors.csv")
    print("wrote: data/review_queue/secrets_required_for_backfill.csv")
    print("wrote: data/exports/rebuild_status.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
