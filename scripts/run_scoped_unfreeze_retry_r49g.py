"""Run R4.9G scoped unfreeze materialization and partial diagnostic rebuild."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from contract_sweeper.pipeline.scoped_partial_rebuild import run_scoped_partial_rebuild
from contract_sweeper.pipeline.scoped_unfreeze_materialization import (
    run_scoped_unfreeze_materialization,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run R4.9G scoped candidate materialization and partial diagnostic rebuild"
    )
    parser.add_argument("--root", default=".", help="Project root")
    args = parser.parse_args()

    root = Path(args.root)
    materialization = run_scoped_unfreeze_materialization(root)
    status = run_scoped_partial_rebuild(root, materialization)

    print(f"r4_9g_gate_passed: {status.get('r4_9g_gate_passed')}")
    print(f"r4_9g_candidates_loaded: {status.get('r4_9g_candidates_loaded')}")
    print(f"r4_9g_candidates_validated: {status.get('r4_9g_candidates_validated')}")
    print(f"r4_9g_candidates_rejected: {status.get('r4_9g_candidates_rejected')}")
    print(f"r4_9g_rows_available: {status.get('r4_9g_rows_available')}")
    print(f"r4_9g_sources_still_blocked: {status.get('r4_9g_sources_still_blocked')}")
    print(
        "r4_9g_partial_rebuild_attempted: "
        f"{status.get('r4_9g_partial_rebuild_attempted')}"
    )
    print(
        "r4_9g_partial_rebuild_succeeded: "
        f"{status.get('r4_9g_partial_rebuild_succeeded')}"
    )
    print(f"r4_9g_partial_rebuild_rows: {status.get('r4_9g_partial_rebuild_rows')}")
    print(f"r4_9g_unique_entities: {status.get('r4_9g_unique_entities')}")
    print(
        "r4_9g_source_lineage_coverage: "
        f"{status.get('r4_9g_source_lineage_coverage')}"
    )
    print(f"r4_9g_output_status: {status.get('r4_9g_output_status')}")
    print(f"production_status: {status.get('production_status')}")
    print(f"r4_9g_downloads_executed: {status.get('r4_9g_downloads_executed')}")
    print(
        "r4_9g_endpoint_retries_executed: "
        f"{status.get('r4_9g_endpoint_retries_executed')}"
    )
    print(
        "r4_9g_production_inputs_staged: "
        f"{status.get('r4_9g_production_inputs_staged')}"
    )
    print(
        "r4_9g_forbidden_artifact_usage: "
        f"{status.get('r4_9g_forbidden_artifact_usage')}"
    )
    print(f"phase_7_8_blocked: {status.get('phase_7_8_blocked')}")
    print(f"downstream_phases_blocked: {status.get('downstream_phases_blocked')}")
    print(json.dumps(status, indent=2))

    print("wrote: data/exports/scoped_unfreeze_status_r4_9g.json")
    print("wrote: data/exports/scoped_unfreeze_candidates_r4_9g.csv")
    print("wrote: data/exports/scoped_unfreeze_validation_report_r4_9g.csv")
    print("wrote: data/exports/scoped_partial_rebuild_status_r4_9g.json")
    print("wrote: data/exports/scoped_partial_rebuild_lineage_r4_9g.csv")
    print("wrote: data/review_queue/sources_still_blocked_r4_9g.csv")
    print("wrote: data/review_queue/downstream_phase_blockers_r4_9g.csv")
    print("wrote: data/exports/rebuild_status.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
