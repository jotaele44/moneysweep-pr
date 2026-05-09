"""Run R4.9A partial diagnostic master rebuild."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from contract_sweeper.pipeline.partial_master_rebuild import run_partial_master_rebuild


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run R4.9A partial diagnostic master rebuild from validated staged inputs"
    )
    parser.add_argument("--root", default=".", help="Project root")
    args = parser.parse_args()

    status = run_partial_master_rebuild(Path(args.root))

    print(f"r4_9a_gate_passed: {status.get('r4_9a_gate_passed')}")
    print(f"r4_9a_validated_inputs_available: {status.get('r4_9a_validated_inputs_available')}")
    print(
        "r4_9a_validated_manifest_records_available: "
        f"{status.get('r4_9a_validated_manifest_records_available')}"
    )
    print(
        "r4_9a_validated_source_files_available: "
        f"{status.get('r4_9a_validated_source_files_available')}"
    )
    print(
        "r4_9a_missing_physical_validated_files: "
        f"{status.get('r4_9a_missing_physical_validated_files')}"
    )
    print(f"r4_9a_missing_inputs: {status.get('r4_9a_missing_inputs')}")
    print(f"r4_9a_external_blockers: {status.get('r4_9a_external_blockers')}")
    print(f"r4_9a_rebuild_attempted: {status.get('r4_9a_rebuild_attempted')}")
    print(f"r4_9a_rebuild_succeeded: {status.get('r4_9a_rebuild_succeeded')}")
    print(f"r4_9a_output_rows: {status.get('r4_9a_output_rows')}")
    print(f"r4_9a_unique_entities: {status.get('r4_9a_unique_entities')}")
    print(f"r4_9a_source_lineage_coverage: {status.get('r4_9a_source_lineage_coverage')}")
    print(f"r4_9a_output_status: {status.get('r4_9a_output_status')}")
    print(f"production_status: {status.get('production_status')}")
    print(f"r4_9a_forbidden_artifact_usage: {status.get('r4_9a_forbidden_artifact_usage')}")
    print(f"phase_7_8_blocked: {status.get('phase_7_8_blocked')}")
    print(json.dumps(status, indent=2))

    print("wrote: data/exports/partial_master_rebuild_status_r4_9a.json")
    print("wrote: data/exports/partial_master_rebuild_inputs_r4_9a.csv")
    print("wrote: data/exports/partial_master_rebuild_gap_report_r4_9a.csv")
    print("wrote: data/exports/partial_master_rebuild_lineage_report_r4_9a.csv")
    print("wrote: data/review_queue/partial_master_missing_inputs_r4_9a.csv")
    print("wrote: data/review_queue/partial_master_blockers_r4_9a.csv")
    print("wrote: data/exports/rebuild_status.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
