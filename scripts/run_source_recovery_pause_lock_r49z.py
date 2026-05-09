"""Run R4.9Z source recovery pause and status lock."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from contract_sweeper.pipeline.source_recovery_pause_lock import run_source_recovery_pause_lock


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run R4.9Z source recovery pause and status lock"
    )
    parser.add_argument("--root", default=".", help="Project root")
    args = parser.parse_args()

    status = run_source_recovery_pause_lock(Path(args.root))

    print(f"r4_9z_gate_passed: {status.get('r4_9z_gate_passed')}")
    print(f"r4_9z_pause_lock_active: {status.get('r4_9z_pause_lock_active')}")
    print(f"r4_9z_unfreeze_candidates: {status.get('r4_9z_unfreeze_candidates')}")
    print(f"r4_9z_sources_still_missing: {status.get('r4_9z_sources_still_missing')}")
    print(f"r4_9z_retry_suppression_active: {status.get('r4_9z_retry_suppression_active')}")
    print(f"r4_9z_downstream_blockers_active: {status.get('r4_9z_downstream_blockers_active')}")
    print(f"r4_9z_downloads_executed: {status.get('r4_9z_downloads_executed')}")
    print(f"r4_9z_rows_ingested: {status.get('r4_9z_rows_ingested')}")
    print(f"r4_9z_production_inputs_staged: {status.get('r4_9z_production_inputs_staged')}")
    print(f"r4_9z_forbidden_artifact_usage: {status.get('r4_9z_forbidden_artifact_usage')}")
    print(f"production_status: {status.get('production_status')}")
    print(f"phase_7_8_blocked: {status.get('phase_7_8_blocked')}")
    print(json.dumps(status, indent=2))

    print("wrote: docs/SOURCE_RECOVERY_PAUSE_STATUS_R4_9Z.md")
    print("wrote: data/exports/source_recovery_pause_status_r4_9z.json")
    print("wrote: data/exports/source_recovery_pause_matrix_r4_9z.csv")
    print("wrote: data/review_queue/source_recovery_resume_conditions_r4_9z.csv")
    print("wrote: data/review_queue/downstream_phase_blockers_r4_9z.csv")
    print("wrote: data/exports/rebuild_status.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
