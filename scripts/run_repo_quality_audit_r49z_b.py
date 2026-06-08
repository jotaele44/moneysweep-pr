"""Run R4.9Z-B repository quality and CI hardening audit."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from contract_sweeper.pipeline.repo_quality_audit import run_repo_quality_audit


def main() -> int:
    parser = argparse.ArgumentParser(description="Run R4.9Z-B repo quality and CI hardening audit")
    parser.add_argument("--root", default=".", help="Project root")
    args = parser.parse_args()

    status = run_repo_quality_audit(Path(args.root))
    print(f"r4_9z_b_gate_passed: {status.get('r4_9z_b_gate_passed')}")
    print(f"production_status: {status.get('production_status')}")
    print(f"phase_7_8_blocked: {status.get('phase_7_8_blocked')}")
    print(f"retry_suppression_active: {status.get('retry_suppression_active')}")
    print(f"downstream_blockers_active: {status.get('downstream_blockers_active')}")
    print(f"downloads_executed: {status.get('downloads_executed')}")
    print(f"rows_ingested: {status.get('rows_ingested')}")
    print(f"production_inputs_staged: {status.get('production_inputs_staged')}")
    print(f"forbidden_artifact_usage: {status.get('forbidden_artifact_usage')}")
    print(f"possible_secret_findings: {status.get('possible_secret_findings')}")
    print(json.dumps(status, indent=2))

    print("wrote: docs/REPO_QUALITY_STATUS_AFTER_R4_9Z.md")
    print("wrote: docs/CI_TESTING_STRATEGY.md")
    print("wrote: data/exports/repo_quality_status_r4_9z_b.json")
    print("wrote: data/exports/repo_quality_matrix_r4_9z_b.csv")
    print("wrote: data/review_queue/repo_hygiene_followups_r4_9z_b.csv")
    print("wrote: data/exports/rebuild_status.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
