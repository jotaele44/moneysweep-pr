"""Run R4.9H2 raw USAspending mapping feasibility review."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from contract_sweeper.pipeline.raw_usaspending_mapping_feasibility import (
    run_raw_usaspending_mapping_feasibility,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run R4.9H2 raw USAspending mapping feasibility review"
    )
    parser.add_argument("--root", default=".", help="Project root")
    args = parser.parse_args()

    status = run_raw_usaspending_mapping_feasibility(Path(args.root))

    print(f"r4_9h2_gate_passed: {status.get('r4_9h2_gate_passed')}")
    print(
        "rejected_candidates_reviewed: "
        f"{status.get('rejected_candidates_reviewed')}"
    )
    print(f"transform_candidates: {status.get('transform_candidates')}")
    print(f"transform_rejects: {status.get('transform_rejects')}")
    print(
        "targets_potentially_unblockable: "
        f"{status.get('targets_potentially_unblockable')}"
    )
    print(
        "targets_still_external_only: "
        f"{status.get('targets_still_external_only')}"
    )
    print(f"downloads_executed: {status.get('downloads_executed')}")
    print(f"rows_ingested: {status.get('rows_ingested')}")
    print(f"production_inputs_staged: {status.get('production_inputs_staged')}")
    print(f"unfreeze_candidates_created: {status.get('unfreeze_candidates_created')}")
    print(f"production_status: {status.get('production_status')}")
    print(f"phase_7_8_blocked: {status.get('phase_7_8_blocked')}")
    print(f"downstream_phases_blocked: {status.get('downstream_phases_blocked')}")
    print(json.dumps(status, indent=2))

    print("wrote: data/exports/raw_usaspending_mapping_feasibility_status_r4_9h2.json")
    print("wrote: data/exports/raw_usaspending_mapping_feasibility_matrix_r4_9h2.csv")
    print("wrote: data/review_queue/raw_usaspending_transform_candidates_r4_9h2.csv")
    print("wrote: data/review_queue/raw_usaspending_transform_rejects_r4_9h2.csv")
    print("wrote: data/review_queue/sources_still_blocked_r4_9h2.csv")
    print("wrote: data/exports/rebuild_status.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
