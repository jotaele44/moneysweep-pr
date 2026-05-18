"""Run R4.9D external blocker freeze and completion gate."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from contract_sweeper.pipeline.external_blocker_freeze import run_external_blocker_freeze


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run R4.9D external blocker freeze and completion gate"
    )
    parser.add_argument("--root", default=".", help="Project root")
    args = parser.parse_args()

    status = run_external_blocker_freeze(Path(args.root))

    print(f"r4_9d_gate_passed: {status.get('r4_9d_gate_passed')}")
    print(f"r4_9d_blockers_frozen: {status.get('r4_9d_blockers_frozen')}")
    print(f"r4_9d_manual_file_required: {status.get('r4_9d_manual_file_required')}")
    print(
        "r4_9d_physical_validated_file_missing: "
        f"{status.get('r4_9d_physical_validated_file_missing')}"
    )
    print(f"r4_9d_retry_suppressed: {status.get('r4_9d_retry_suppressed')}")
    print(f"r4_9d_downstream_phases_blocked: {status.get('r4_9d_downstream_phases_blocked')}")
    print(
        "r4_9d_unfreeze_requirements_written: "
        f"{status.get('r4_9d_unfreeze_requirements_written')}"
    )
    print(f"r4_9d_downloads_executed: {status.get('r4_9d_downloads_executed')}")
    print(f"r4_9d_rows_ingested: {status.get('r4_9d_rows_ingested')}")
    print(f"r4_9d_production_inputs_staged: {status.get('r4_9d_production_inputs_staged')}")
    print(f"r4_9d_forbidden_artifact_usage: {status.get('r4_9d_forbidden_artifact_usage')}")
    print(f"production_status: {status.get('production_status')}")
    print(f"phase_7_8_blocked: {status.get('phase_7_8_blocked')}")
    print(json.dumps(status, indent=2))

    print("wrote: data/exports/external_blocker_freeze_status_r4_9d.json")
    print("wrote: data/exports/external_blocker_freeze_matrix_r4_9d.csv")
    print("wrote: data/exports/source_recovery_unfreeze_requirements_r4_9d.md")
    print("wrote: data/review_queue/source_delivery_required_r4_9d.csv")
    print("wrote: data/review_queue/retry_suppression_queue_r4_9d.csv")
    print("wrote: data/review_queue/downstream_phase_blockers_r4_9d.csv")
    print("wrote: data/exports/rebuild_status.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
