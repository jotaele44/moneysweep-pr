"""Run R4.9F source delivery watch and unfreeze guard."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from contract_sweeper.pipeline.source_delivery_watch import run_source_delivery_watch


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run R4.9F source delivery watch and unfreeze guard"
    )
    parser.add_argument("--root", default=".", help="Project root")
    args = parser.parse_args()

    status = run_source_delivery_watch(Path(args.root))

    print(f"r4_9f_gate_passed: {status.get('r4_9f_gate_passed')}")
    print(f"r4_9f_checklist_rows_checked: {status.get('r4_9f_checklist_rows_checked')}")
    print(f"r4_9f_candidate_files_found: {status.get('r4_9f_candidate_files_found')}")
    print(f"r4_9f_unfreeze_candidates: {status.get('r4_9f_unfreeze_candidates')}")
    print(f"r4_9f_sources_still_missing: {status.get('r4_9f_sources_still_missing')}")
    print(
        "r4_9f_retry_suppression_preserved: "
        f"{status.get('r4_9f_retry_suppression_preserved')}"
    )
    print(
        "r4_9f_downstream_blockers_preserved: "
        f"{status.get('r4_9f_downstream_blockers_preserved')}"
    )
    print(f"r4_9f_downloads_executed: {status.get('r4_9f_downloads_executed')}")
    print(f"r4_9f_rows_ingested: {status.get('r4_9f_rows_ingested')}")
    print(f"r4_9f_production_inputs_staged: {status.get('r4_9f_production_inputs_staged')}")
    print(f"r4_9f_forbidden_artifact_usage: {status.get('r4_9f_forbidden_artifact_usage')}")
    print(f"production_status: {status.get('production_status')}")
    print(f"phase_7_8_blocked: {status.get('phase_7_8_blocked')}")
    print(json.dumps(status, indent=2))

    print("wrote: data/exports/source_delivery_watch_status_r4_9f.json")
    print("wrote: data/exports/source_delivery_watch_results_r4_9f.csv")
    print("wrote: data/review_queue/unfreeze_candidates_r4_9f.csv")
    print("wrote: data/review_queue/source_delivery_still_missing_r4_9f.csv")
    print("wrote: data/review_queue/downstream_phase_blockers_r4_9f.csv")
    print("wrote: data/exports/rebuild_status.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
