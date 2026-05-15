"""Run R4.8C source blocker remediation and manual fallback planning."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from contract_sweeper.pipeline.backfill_failure_remediation import run_backfill_failure_remediation


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run source blocker remediation analysis for R4.8C"
    )
    parser.add_argument("--root", default=".", help="Project root directory")
    parser.add_argument(
        "--retry-attempted",
        action="store_true",
        help="Mark that a narrow retry attempt was performed (default false).",
    )
    parser.add_argument(
        "--retry-scope",
        default="",
        help="Optional description of retry scope when --retry-attempted is set.",
    )
    args = parser.parse_args()

    result = run_backfill_failure_remediation(
        Path(args.root),
        retry_attempted=bool(args.retry_attempted),
        retry_scope=str(args.retry_scope or ""),
    )

    print(f"r4_8c_gate_passed: {result.get('r4_8c_gate_passed')}")
    print(f"r4_8c_total_failed_sources: {result.get('r4_8c_total_failed_sources')}")
    print(f"r4_8c_primary_blocker_counts: {result.get('r4_8c_primary_blocker_counts')}")
    print(f"r4_8c_schema_remediation_count: {result.get('r4_8c_schema_remediation_count')}")
    print(f"r4_8c_manual_fallback_count: {result.get('r4_8c_manual_fallback_count')}")
    print(f"r4_8c_producer_fix_count: {result.get('r4_8c_producer_fix_count')}")
    print(f"r4_8c_endpoint_review_count: {result.get('r4_8c_endpoint_review_count')}")
    print(f"r4_8c_retry_order_count: {result.get('r4_8c_retry_order_count')}")
    print(f"r4_8c_downloads_executed: {result.get('r4_8c_downloads_executed')}")
    print(f"r4_8c_rows_ingested: {result.get('r4_8c_rows_ingested')}")
    print(f"r4_8c_production_inputs_staged: {result.get('r4_8c_production_inputs_staged')}")
    print(
        "r4_8c_validated_source_manifests_written: "
        f"{result.get('r4_8c_validated_source_manifests_written')}"
    )
    print(f"phase_7_8_blocked: {result.get('phase_7_8_blocked')}")
    print(json.dumps(result, indent=2))

    print("wrote: data/exports/backfill_failure_remediation_matrix_r4_8c.csv")
    print("wrote: data/exports/backfill_failure_remediation_status_r4_8c.json")
    print("wrote: data/review_queue/source_producer_fix_queue_r4_8c.csv")
    print("wrote: data/review_queue/schema_remediation_queue_r4_8c.csv")
    print("wrote: data/review_queue/manual_fallback_execution_queue_r4_8c.csv")
    print("wrote: data/review_queue/source_endpoint_review_queue_r4_8c.csv")
    print("wrote: data/review_queue/backfill_retry_order_r4_8c.csv")
    print("wrote: data/exports/rebuild_status.json")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
