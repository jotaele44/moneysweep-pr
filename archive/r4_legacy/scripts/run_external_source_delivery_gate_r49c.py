"""Run R4.9C external source delivery gate."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from contract_sweeper.pipeline.external_source_delivery_gate import run_external_source_delivery_gate


def main() -> int:
    parser = argparse.ArgumentParser(description="Run R4.9C external source delivery gate")
    parser.add_argument("--root", default=".", help="Project root")
    args = parser.parse_args()

    status = run_external_source_delivery_gate(Path(args.root))

    print(f"r4_9c_gate_passed: {status.get('r4_9c_gate_passed')}")
    print(f"r4_9c_delivery_requests_checked: {status.get('r4_9c_delivery_requests_checked')}")
    print(f"r4_9c_files_found: {status.get('r4_9c_files_found')}")
    print(f"r4_9c_files_validated: {status.get('r4_9c_files_validated')}")
    print(f"r4_9c_files_materialized: {status.get('r4_9c_files_materialized')}")
    print(f"r4_9c_validated_source_manifests_total: {status.get('r4_9c_validated_source_manifests_total')}")
    print(f"r4_9c_new_validated_source_manifests: {status.get('r4_9c_new_validated_source_manifests')}")
    print(f"r4_9c_rows_available_total: {status.get('r4_9c_rows_available_total')}")
    print(f"r4_9c_new_rows_available: {status.get('r4_9c_new_rows_available')}")
    print(f"r4_9c_delivery_blockers: {status.get('r4_9c_delivery_blockers')}")
    print(f"r4_9c_manual_files_still_required: {status.get('r4_9c_manual_files_still_required')}")
    print(
        "r4_9c_physical_validated_files_still_missing: "
        f"{status.get('r4_9c_physical_validated_files_still_missing')}"
    )
    print(f"r4_9c_forbidden_artifact_usage: {status.get('r4_9c_forbidden_artifact_usage')}")
    print(f"production_status: {status.get('production_status')}")
    print(f"phase_7_8_blocked: {status.get('phase_7_8_blocked')}")
    print(json.dumps(status, indent=2))

    print("wrote: data/exports/external_source_delivery_status_r4_9c.json")
    print("wrote: data/exports/external_source_delivery_results_r4_9c.csv")
    print("wrote: data/exports/delivered_source_validation_report_r4_9c.csv")
    print("wrote: data/exports/validated_source_manifest_inventory_r4_9c.csv")
    print("wrote: data/review_queue/external_source_delivery_blockers_r4_9c.csv")
    print("wrote: data/review_queue/manual_files_still_required_r4_9c.csv")
    print("wrote: data/review_queue/physical_validated_files_still_missing_r4_9c.csv")
    print("wrote: data/review_queue/backfill_retry_order_r4_9c.csv")
    print("wrote: data/exports/rebuild_status.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
