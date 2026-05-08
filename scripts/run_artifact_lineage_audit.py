"""Run R1 artifact lineage and cache-reuse audit."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from contract_sweeper.validation.cache_audit import run_audit


def main() -> int:
    parser = argparse.ArgumentParser(description="Run R1 artifact lineage + cache audit")
    parser.add_argument("--root", default=".", help="Project root directory")
    args = parser.parse_args()

    result = run_audit(Path(args.root))
    print(f"reports_recomputed: {result['reports_recomputed']}")
    print(f"report_regeneration_status: {result['report_regeneration_status']}")
    print(f"r1_gate_passed: {result['r1_gate_passed']}")
    print(f"phase_7_8_blocked: {result['phase_7_8_blocked']}")
    print(json.dumps(result, indent=2))
    print("wrote: data/exports/artifact_lineage_audit.csv")
    print("wrote: data/exports/cache_reuse_audit.csv")
    print("wrote: data/exports/rebuild_status.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

