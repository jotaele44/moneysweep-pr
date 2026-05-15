"""Run R4.8H manual fulfillment and credentialed endpoint retry."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from contract_sweeper.pipeline.final_backfill_retry import run_final_backfill_retry


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run R4.8H manual-file fulfillment and credentialed endpoint/producer retries"
    )
    parser.add_argument("--root", default=".", help="Project root")
    parser.add_argument(
        "--command-timeout-seconds",
        type=int,
        default=20,
        help="Timeout in seconds per retry command",
    )
    args = parser.parse_args()

    status = run_final_backfill_retry(
        Path(args.root),
        command_timeout_seconds=max(1, int(args.command_timeout_seconds)),
    )

    print(f"r4_8h_gate_passed: {status.get('r4_8h_gate_passed')}")
    print(f"r4_8h_manual_requests_checked: {status.get('r4_8h_manual_requests_checked')}")
    print(f"r4_8h_manual_files_found: {status.get('r4_8h_manual_files_found')}")
    print(f"r4_8h_manual_files_validated: {status.get('r4_8h_manual_files_validated')}")
    print(f"r4_8h_manual_files_still_required: {status.get('r4_8h_manual_files_still_required')}")
    print(f"r4_8h_credential_requests_checked: {status.get('r4_8h_credential_requests_checked')}")
    print(f"r4_8h_credentials_available: {status.get('r4_8h_credentials_available')}")
    print(f"r4_8h_credentials_still_required: {status.get('r4_8h_credentials_still_required')}")
    print(f"r4_8h_endpoint_retries_attempted: {status.get('r4_8h_endpoint_retries_attempted')}")
    print(f"r4_8h_endpoint_retries_successful: {status.get('r4_8h_endpoint_retries_successful')}")
    print(f"r4_8h_producer_patches_applied: {status.get('r4_8h_producer_patches_applied')}")
    print(f"r4_8h_producer_retries_attempted: {status.get('r4_8h_producer_retries_attempted')}")
    print(f"r4_8h_producer_retries_successful: {status.get('r4_8h_producer_retries_successful')}")
    print(f"r4_8h_rows_ingested_total: {status.get('r4_8h_rows_ingested_total')}")
    print(
        "r4_8h_production_inputs_staged_total: "
        f"{status.get('r4_8h_production_inputs_staged_total')}"
    )
    print(
        "r4_8h_validated_source_manifests_total: "
        f"{status.get('r4_8h_validated_source_manifests_total')}"
    )
    print(f"r4_8h_new_rows_ingested: {status.get('r4_8h_new_rows_ingested')}")
    print(f"r4_8h_new_production_inputs_staged: {status.get('r4_8h_new_production_inputs_staged')}")
    print(
        "r4_8h_new_validated_source_manifests: "
        f"{status.get('r4_8h_new_validated_source_manifests')}"
    )
    print(f"r4_8h_forbidden_artifact_usage: {status.get('r4_8h_forbidden_artifact_usage')}")
    print(f"phase_7_8_blocked: {status.get('phase_7_8_blocked')}")
    print(json.dumps(status, indent=2))

    print("wrote: data/exports/manual_fulfillment_endpoint_retry_status_r4_8h.json")
    print("wrote: data/exports/manual_fulfillment_results_r4_8h.csv")
    print("wrote: data/exports/credentialed_endpoint_retry_results_r4_8h.csv")
    print("wrote: data/exports/final_backfill_retry_results_r4_8h.csv")
    print("wrote: data/exports/validated_source_manifest_inventory_r4_8h.csv")
    print("wrote: data/review_queue/manual_files_still_required_r4_8h.csv")
    print("wrote: data/review_queue/credentials_still_required_r4_8h.csv")
    print("wrote: data/review_queue/endpoints_still_blocked_r4_8h.csv")
    print("wrote: data/review_queue/producers_still_blocked_r4_8h.csv")
    print("wrote: data/review_queue/backfill_retry_order_r4_8h.csv")
    print("wrote: data/exports/rebuild_status.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
