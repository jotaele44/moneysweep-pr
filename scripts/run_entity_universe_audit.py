"""Run R2 entity universe and collapse audit."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from contract_sweeper.validation.entity_universe_audit import run_audit


def main() -> int:
    parser = argparse.ArgumentParser(description="Run R2 entity universe and collapse audit")
    parser.add_argument("--root", default=".", help="Project root directory")
    args = parser.parse_args()

    result = run_audit(Path(args.root))
    print(f"unique_normalized_entity_count: {result.get('unique_normalized_entity_count')}")
    print(f"parent_uei_coverage: {result.get('parent_uei_coverage')}")
    print(f"high_value_overcollapse_suspect_count: {result.get('high_value_overcollapse_suspect_count')}")
    print(f"high_value_unresolved_count: {result.get('high_value_unresolved_count')}")
    print(f"inferred_18_entity_collapse_stage: {result.get('inferred_18_entity_collapse_stage')}")
    print(f"r2_gate_passed: {result.get('r2_gate_passed')}")
    print(f"phase_7_8_blocked: {result.get('phase_7_8_blocked')}")
    print(json.dumps(result, indent=2))
    print("wrote: data/exports/entity_universe_audit.csv")
    print("wrote: data/exports/entity_collapse_diagnostics.csv")
    print("wrote: data/review_queue/suspect_entity_collapses.csv")
    print("wrote: data/review_queue/high_value_unresolved_entities.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

