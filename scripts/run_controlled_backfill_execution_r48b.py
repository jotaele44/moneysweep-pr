"""Run R4.8B controlled real backfill execution."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from contract_sweeper.pipeline.controlled_backfill_execution import run_controlled_backfill_execution


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run controlled real backfill execution for R4.8B"
    )
    parser.add_argument("--root", default=".", help="Project root directory")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Do not execute producer commands; emit explicit skipped statuses.",
    )
    parser.add_argument(
        "--command-timeout-seconds",
        type=int,
        default=120,
        help="Timeout in seconds for each producer command attempt.",
    )
    parser.add_argument(
        "--validation-timeout-seconds",
        type=int,
        default=60,
        help="Timeout in seconds for each validation command.",
    )
    args = parser.parse_args()

    result = run_controlled_backfill_execution(
        Path(args.root),
        execute_downloads=not bool(args.dry_run),
        command_timeout_s=max(1, int(args.command_timeout_seconds)),
        validation_timeout_s=max(1, int(args.validation_timeout_seconds)),
    )

    print(f"r4_8b_gate_passed: {result.get('r4_8b_gate_passed')}")
    print(f"r4_8b_total_sources: {result.get('r4_8b_total_sources')}")
    print(f"r4_8b_attempted_sources: {result.get('r4_8b_attempted_sources')}")
    print(f"r4_8b_successful_sources: {result.get('r4_8b_successful_sources')}")
    print(f"r4_8b_failed_sources: {result.get('r4_8b_failed_sources')}")
    print(f"r4_8b_no_data_sources: {result.get('r4_8b_no_data_sources')}")
    print(f"r4_8b_credential_failures: {result.get('r4_8b_credential_failures')}")
    print(f"r4_8b_schema_failures: {result.get('r4_8b_schema_failures')}")
    print(f"r4_8b_manual_fallback_required: {result.get('r4_8b_manual_fallback_required')}")
    print(f"r4_8b_rows_ingested: {result.get('r4_8b_rows_ingested')}")
    print(f"r4_8b_production_inputs_staged: {result.get('r4_8b_production_inputs_staged')}")
    print(
        "r4_8b_validated_source_manifests_written: "
        f"{result.get('r4_8b_validated_source_manifests_written')}"
    )
    print(f"r4_8b_forbidden_artifact_usage: {result.get('r4_8b_forbidden_artifact_usage')}")
    print(f"phase_7_8_blocked: {result.get('phase_7_8_blocked')}")
    print(json.dumps(result, indent=2))

    print("wrote: data/exports/controlled_backfill_execution_results_r4_8b.csv")
    print("wrote: data/exports/controlled_backfill_execution_status_r4_8b.json")
    print("wrote: data/exports/validated_source_manifest_inventory_r4_8b.csv")
    print("wrote: data/review_queue/controlled_backfill_execution_failures_r4_8b.csv")
    print("wrote: data/review_queue/no_data_sources_r4_8b.csv")
    print("wrote: data/review_queue/schema_failures_r4_8b.csv")
    print("wrote: data/review_queue/manual_fallback_required_r4_8b.csv")
    print("wrote: data/review_queue/credential_failures_r4_8b.csv")
    print("wrote: data/exports/rebuild_status.json")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
