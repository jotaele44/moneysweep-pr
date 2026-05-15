"""Run R4.8D targeted producer patch + schema alignment retry."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from contract_sweeper.pipeline.targeted_backfill_retry import run_targeted_backfill_retry


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run targeted retry for actionable R4.8C sources"
    )
    parser.add_argument("--root", default=".", help="Project root directory")
    parser.add_argument(
        "--command-timeout-seconds",
        type=int,
        default=30,
        help="Timeout for each producer command.",
    )
    parser.add_argument(
        "--validation-timeout-seconds",
        type=int,
        default=30,
        help="Timeout for each validation command.",
    )
    args = parser.parse_args()

    result = run_targeted_backfill_retry(
        Path(args.root),
        command_timeout_s=max(1, int(args.command_timeout_seconds)),
        validation_timeout_s=max(1, int(args.validation_timeout_seconds)),
    )

    print(f"r4_8d_gate_passed: {result.get('r4_8d_gate_passed')}")
    print(f"r4_8d_total_sources_considered: {result.get('r4_8d_total_sources_considered')}")
    print(f"r4_8d_sources_retried: {result.get('r4_8d_sources_retried')}")
    print(f"r4_8d_successful_sources: {result.get('r4_8d_successful_sources')}")
    print(f"r4_8d_failed_sources: {result.get('r4_8d_failed_sources')}")
    print(f"r4_8d_schema_alignments_added: {result.get('r4_8d_schema_alignments_added')}")
    print(f"r4_8d_producer_patches_applied: {result.get('r4_8d_producer_patches_applied')}")
    print(f"r4_8d_rows_ingested: {result.get('r4_8d_rows_ingested')}")
    print(f"r4_8d_production_inputs_staged: {result.get('r4_8d_production_inputs_staged')}")
    print(
        "r4_8d_validated_source_manifests_written: "
        f"{result.get('r4_8d_validated_source_manifests_written')}"
    )
    print(f"r4_8d_manual_fallback_remaining: {result.get('r4_8d_manual_fallback_remaining')}")
    print(f"r4_8d_unresolved_endpoint_failures: {result.get('r4_8d_unresolved_endpoint_failures')}")
    print(f"r4_8d_unresolved_schema_failures: {result.get('r4_8d_unresolved_schema_failures')}")
    print(f"r4_8d_unresolved_producer_failures: {result.get('r4_8d_unresolved_producer_failures')}")
    print(f"r4_8d_forbidden_artifact_usage: {result.get('r4_8d_forbidden_artifact_usage')}")
    print(f"phase_7_8_blocked: {result.get('phase_7_8_blocked')}")
    print(json.dumps(result, indent=2))

    print("wrote: data/exports/targeted_backfill_retry_results_r4_8d.csv")
    print("wrote: data/exports/targeted_backfill_retry_status_r4_8d.json")
    print("wrote: data/exports/schema_alignment_report_r4_8d.csv")
    print("wrote: data/exports/validated_source_manifest_inventory_r4_8d.csv")
    print("wrote: data/review_queue/unresolved_producer_failures_r4_8d.csv")
    print("wrote: data/review_queue/unresolved_schema_failures_r4_8d.csv")
    print("wrote: data/review_queue/unresolved_endpoint_failures_r4_8d.csv")
    print("wrote: data/review_queue/manual_fallback_remaining_r4_8d.csv")
    print("wrote: data/review_queue/backfill_retry_order_r4_8d.csv")
    print("wrote: data/exports/rebuild_status.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
