"""Run R4.8A controlled backfill execution readiness audit."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from contract_sweeper.pipeline.backfill_readiness_audit import run_backfill_readiness_audit


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run controlled backfill readiness audit for R4.8A"
    )
    parser.add_argument("--root", default=".", help="Project root directory")
    args = parser.parse_args()

    result = run_backfill_readiness_audit(Path(args.root))

    print(f"r4_8a_gate_passed: {result.get('r4_8a_gate_passed')}")
    print(f"phase_7_8_blocked: {result.get('phase_7_8_blocked')}")
    print(f"r4_8a_total_sources: {result.get('r4_8a_total_sources')}")
    print(f"r4_8a_ready_for_execute_downloads_count: {result.get('r4_8a_ready_for_execute_downloads_count')}")
    print(f"r4_8a_requires_credentials_count: {result.get('r4_8a_requires_credentials_count')}")
    print(f"r4_8a_requires_manual_file_count: {result.get('r4_8a_requires_manual_file_count')}")
    print(f"r4_8a_requires_schema_mapping_count: {result.get('r4_8a_requires_schema_mapping_count')}")
    print(f"r4_8a_requires_producer_script_count: {result.get('r4_8a_requires_producer_script_count')}")
    print(f"r4_8a_blocked_count: {result.get('r4_8a_blocked_count')}")
    print(f"r4_8a_downloads_executed: {result.get('r4_8a_downloads_executed')}")
    print(f"r4_8a_rows_ingested: {result.get('r4_8a_rows_ingested')}")
    print(f"r4_8a_production_inputs_staged: {result.get('r4_8a_production_inputs_staged')}")
    print(f"r4_8a_validated_source_manifests_written: {result.get('r4_8a_validated_source_manifests_written')}")
    print(f"r4_8a_planning_manifest_count: {result.get('r4_8a_planning_manifest_count')}")
    print(f"row_fabrication_policy: {result.get('row_fabrication_policy')}")
    print(json.dumps(result, indent=2))
    print("wrote: data/exports/backfill_readiness_matrix_r4_8a.csv")
    print("wrote: data/exports/backfill_readiness_status_r4_8a.json")
    print("wrote: data/review_queue/backfill_execution_blockers_r4_8a.csv")
    print("wrote: data/review_queue/credentials_required_r4_8a.csv")
    print("wrote: data/review_queue/manual_files_required_r4_8a.csv")
    print("wrote: data/review_queue/schema_required_r4_8a.csv")
    print("wrote: data/exports/rebuild_status.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
