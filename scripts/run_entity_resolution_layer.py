"""Run Phase 4 entity resolution and parent collapse outputs."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from contract_sweeper.resolution import run_entity_resolution


def main() -> int:
    parser = argparse.ArgumentParser(description="Run canonical entity resolution layer")
    parser.add_argument("--input", help="Optional contracts master path (.csv or .parquet)")
    parser.add_argument("--review-threshold", type=float, default=0.85)
    parser.add_argument("--fuzzy-high", type=float, default=93.0)
    parser.add_argument("--fuzzy-medium", type=float, default=88.0)
    parser.add_argument("--high-value-threshold", type=float, default=1000000.0)
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parent.parent
    input_path = Path(args.input).resolve() if args.input else None

    artifacts = run_entity_resolution(
        project_root=project_root,
        input_path=input_path,
        review_threshold=float(args.review_threshold),
        fuzzy_threshold_high=float(args.fuzzy_high),
        fuzzy_threshold_medium=float(args.fuzzy_medium),
        high_value_threshold=float(args.high_value_threshold),
    )

    print(f"entities_resolved.csv: {artifacts.entities_resolved_csv}")
    print(f"alias_registry.json: {artifacts.alias_registry_json}")
    print(f"low_confidence_review_queue.csv: {artifacts.low_confidence_review_queue_csv}")
    print(f"high_value_unresolved_entities.csv: {artifacts.high_value_unresolved_csv}")
    print(f"summary: {artifacts.summary_json}")
    print(f"resolution_rate: {artifacts.summary.get('resolution_rate', 0.0)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
