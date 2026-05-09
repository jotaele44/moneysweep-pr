"""Run R4.9B source materialization and partial rebuild retry."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from contract_sweeper.pipeline.partial_rebuild_retry import run_partial_rebuild_retry
from contract_sweeper.pipeline.source_materialization import run_source_materialization


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run R4.9B validated source materialization and partial diagnostic rebuild retry"
    )
    parser.add_argument("--root", default=".", help="Project root")
    args = parser.parse_args()

    root = Path(args.root)
    materialization = run_source_materialization(root)
    status = run_partial_rebuild_retry(root, materialization)

    print(f"r4_9b_gate_passed: {status.get('r4_9b_gate_passed')}")
    print(f"r4_9b_manifest_records_checked: {status.get('r4_9b_manifest_records_checked')}")
    print(f"r4_9b_files_materialized: {status.get('r4_9b_files_materialized')}")
    print(f"r4_9b_files_hash_validated: {status.get('r4_9b_files_hash_validated')}")
    print(f"r4_9b_materialization_blockers: {status.get('r4_9b_materialization_blockers')}")
    print(f"r4_9b_rebuild_attempted: {status.get('r4_9b_rebuild_attempted')}")
    print(f"r4_9b_rebuild_succeeded: {status.get('r4_9b_rebuild_succeeded')}")
    print(f"r4_9b_output_rows: {status.get('r4_9b_output_rows')}")
    print(f"r4_9b_unique_entities: {status.get('r4_9b_unique_entities')}")
    print(f"r4_9b_source_lineage_coverage: {status.get('r4_9b_source_lineage_coverage')}")
    print(f"r4_9b_output_status: {status.get('r4_9b_output_status')}")
    print(f"production_status: {status.get('production_status')}")
    print(f"r4_9b_forbidden_artifact_usage: {status.get('r4_9b_forbidden_artifact_usage')}")
    print(f"phase_7_8_blocked: {status.get('phase_7_8_blocked')}")
    print(json.dumps(status, indent=2))

    print("wrote: data/exports/source_materialization_status_r4_9b.json")
    print("wrote: data/exports/source_materialization_results_r4_9b.csv")
    print("wrote: data/exports/partial_rebuild_retry_status_r4_9b.json")
    print("wrote: data/exports/partial_rebuild_retry_inputs_r4_9b.csv")
    print("wrote: data/exports/partial_rebuild_retry_lineage_report_r4_9b.csv")
    print("wrote: data/review_queue/source_materialization_blockers_r4_9b.csv")
    print("wrote: data/review_queue/partial_rebuild_retry_blockers_r4_9b.csv")
    print("wrote: data/exports/rebuild_status.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
