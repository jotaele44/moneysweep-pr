"""Run R4.9E source delivery handoff and operator package generation."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from contract_sweeper.pipeline.source_delivery_handoff import run_source_delivery_handoff


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run R4.9E source delivery README and operator handoff"
    )
    parser.add_argument("--root", default=".", help="Project root")
    args = parser.parse_args()

    status = run_source_delivery_handoff(Path(args.root))

    print(f"r4_9e_gate_passed: {status.get('r4_9e_gate_passed')}")
    print(f"r4_9e_handoff_written: {status.get('r4_9e_handoff_written')}")
    print(f"r4_9e_delivery_checklist_count: {status.get('r4_9e_delivery_checklist_count')}")
    print(f"r4_9e_unfreeze_trigger_count: {status.get('r4_9e_unfreeze_trigger_count')}")
    print(
        "r4_9e_retry_suppression_preserved: "
        f"{status.get('r4_9e_retry_suppression_preserved')}"
    )
    print(
        "r4_9e_downstream_blockers_preserved: "
        f"{status.get('r4_9e_downstream_blockers_preserved')}"
    )
    print(f"r4_9e_downloads_executed: {status.get('r4_9e_downloads_executed')}")
    print(f"r4_9e_rows_ingested: {status.get('r4_9e_rows_ingested')}")
    print(f"r4_9e_production_inputs_staged: {status.get('r4_9e_production_inputs_staged')}")
    print(f"r4_9e_forbidden_artifact_usage: {status.get('r4_9e_forbidden_artifact_usage')}")
    print(f"production_status: {status.get('production_status')}")
    print(f"phase_7_8_blocked: {status.get('phase_7_8_blocked')}")
    print(json.dumps(status, indent=2))

    print("wrote: docs/SOURCE_DELIVERY_HANDOFF_R4_9E.md")
    print("wrote: docs/EXTERNAL_BLOCKER_FREEZE_STATUS_R4_9E.md")
    print("wrote: data/exports/source_delivery_handoff_status_r4_9e.json")
    print("wrote: data/exports/source_delivery_handoff_summary_r4_9e.csv")
    print("wrote: data/review_queue/source_delivery_checklist_r4_9e.csv")
    print("wrote: data/review_queue/unfreeze_trigger_conditions_r4_9e.csv")
    print("wrote: data/exports/rebuild_status.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
