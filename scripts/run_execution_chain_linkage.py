"""Run Phase 5 execution-chain linkage layer."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from contract_sweeper.linkage import run_chain_linkage
from contract_sweeper.runtime import load_runtime_config, load_schema_registry


def main() -> int:
    parser = argparse.ArgumentParser(description="Run execution chain linkage")
    parser.add_argument("--contracts-input", help="Optional contracts input path (.csv or .parquet)")
    parser.add_argument("--entities-input", help="Optional entities_resolved.csv path")
    parser.add_argument("--review-threshold", type=float, default=0.85)
    parser.add_argument("--fuzzy-high", type=float, default=93.0)
    parser.add_argument("--fuzzy-medium", type=float, default=88.0)
    parser.add_argument("--linkage-target", type=float, default=0.90)
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parent.parent
    runtime_config = load_runtime_config(project_root=project_root)
    schema_registry = load_schema_registry(runtime_config.configs_dir / "schema_registry.yaml")

    artifacts = run_chain_linkage(
        project_root=project_root,
        schema_registry=schema_registry,
        contracts_input_path=Path(args.contracts_input).resolve() if args.contracts_input else None,
        entities_resolved_path=Path(args.entities_input).resolve() if args.entities_input else None,
        review_threshold=float(args.review_threshold),
        fuzzy_high=float(args.fuzzy_high),
        fuzzy_medium=float(args.fuzzy_medium),
        linkage_target=float(args.linkage_target),
    )

    print(f"execution_chain_master.csv: {artifacts.execution_chain_master_csv}")
    print(f"execution_chain_per_asset.csv: {artifacts.execution_chain_per_asset_csv}")
    print(f"execution_chain_review_queue.csv: {artifacts.low_confidence_review_queue_csv}")
    print(f"summary: {artifacts.summary_json}")
    print(f"cross_layer_linkage_rate: {artifacts.summary.get('cross_layer_linkage_rate', 0.0)}")
    print(f"target_met: {artifacts.summary.get('target_met', False)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
