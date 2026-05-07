"""Run Phase 7 probabilistic risk signal engine."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from contract_sweeper.risk import run_risk_signal_engine
from contract_sweeper.runtime.schema_registry import load_schema_registry


def main() -> int:
    parser = argparse.ArgumentParser(description="Run probabilistic risk signal engine")
    parser.add_argument("--contracts", help="Optional contracts_master CSV/parquet path")
    parser.add_argument("--execution-chain", help="Optional execution_chain_master.csv path")
    parser.add_argument("--entities", help="Optional entities_resolved.csv path")
    parser.add_argument("--financial-flows", help="Optional financial_flows_master parquet/CSV path")
    parser.add_argument("--asset-control-graph", help="Optional asset-control graph context CSV/parquet path")
    parser.add_argument("--lobbying-tables", help="Optional normalized lobbying/cabilderos context CSV/parquet path")
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parent.parent
    schema_registry = load_schema_registry(project_root / "configs" / "schema_registry.yaml")
    artifacts = run_risk_signal_engine(
        project_root=project_root,
        schema_registry=schema_registry,
        contracts_path=Path(args.contracts).resolve() if args.contracts else None,
        execution_chain_path=Path(args.execution_chain).resolve() if args.execution_chain else None,
        entities_resolved_path=Path(args.entities).resolve() if args.entities else None,
        financial_flows_path=Path(args.financial_flows).resolve() if args.financial_flows else None,
        asset_control_graph_path=Path(args.asset_control_graph).resolve() if args.asset_control_graph else None,
        lobbying_tables_path=Path(args.lobbying_tables).resolve() if args.lobbying_tables else None,
    )

    print(f"risk_alerts_master.csv: {artifacts.risk_alerts_master_csv}")
    print(f"high_risk_projects.geojson: {artifacts.high_risk_projects_geojson}")
    print(f"entity_behavior_history.parquet: {artifacts.entity_behavior_history_parquet}")
    print(f"risk_review_queue.csv: {artifacts.risk_review_queue_csv}")
    print(f"summary: {artifacts.summary_json}")
    print(f"rows: {artifacts.summary.get('rows_total', 0)}")
    print(f"review_queue_total: {artifacts.summary.get('review_queue_total', 0)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
