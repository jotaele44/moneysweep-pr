"""Run R4.9H raw USAspending source discovery."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from contract_sweeper.pipeline.raw_usaspending_discovery import (
    run_raw_usaspending_discovery,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run R4.9H raw USAspending discovery and candidate validation"
    )
    parser.add_argument("--root", default=".", help="Project root")
    args = parser.parse_args()

    status = run_raw_usaspending_discovery(Path(args.root))

    print(f"r4_9h_gate_passed: {status.get('r4_9h_gate_passed')}")
    print(f"r4_9h_raw_files_scanned: {status.get('r4_9h_raw_files_scanned')}")
    print(
        "r4_9h_usaspending_like_files_found: "
        f"{status.get('r4_9h_usaspending_like_files_found')}"
    )
    print(f"r4_9h_candidate_matches: {status.get('r4_9h_candidate_matches')}")
    print(f"r4_9h_candidates_validated: {status.get('r4_9h_candidates_validated')}")
    print(f"r4_9h_candidates_rejected: {status.get('r4_9h_candidates_rejected')}")
    print(f"r4_9h_new_unfreeze_candidates: {status.get('r4_9h_new_unfreeze_candidates')}")
    print(f"r4_9h_sources_still_blocked: {status.get('r4_9h_sources_still_blocked')}")
    print(f"r4_9h_downloads_executed: {status.get('r4_9h_downloads_executed')}")
    print(
        "r4_9h_endpoint_retries_executed: "
        f"{status.get('r4_9h_endpoint_retries_executed')}"
    )
    print(f"r4_9h_rows_ingested: {status.get('r4_9h_rows_ingested')}")
    print(
        "r4_9h_production_inputs_staged: "
        f"{status.get('r4_9h_production_inputs_staged')}"
    )
    print(
        "r4_9h_forbidden_artifact_usage: "
        f"{status.get('r4_9h_forbidden_artifact_usage')}"
    )
    print(f"production_status: {status.get('production_status')}")
    print(f"phase_7_8_blocked: {status.get('phase_7_8_blocked')}")
    print(f"downstream_phases_blocked: {status.get('downstream_phases_blocked')}")
    print(json.dumps(status, indent=2))

    print("wrote: data/exports/raw_usaspending_discovery_status_r4_9h.json")
    print("wrote: data/exports/raw_usaspending_file_inventory_r4_9h.csv")
    print("wrote: data/exports/raw_usaspending_candidate_matches_r4_9h.csv")
    print("wrote: data/exports/raw_usaspending_validation_report_r4_9h.csv")
    print("wrote: data/review_queue/raw_usaspending_unfreeze_candidates_r4_9h.csv")
    print("wrote: data/review_queue/raw_usaspending_rejected_candidates_r4_9h.csv")
    print("wrote: data/review_queue/sources_still_blocked_r4_9h.csv")
    print("wrote: data/exports/rebuild_status.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
