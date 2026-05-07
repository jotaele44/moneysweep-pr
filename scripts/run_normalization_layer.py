"""Run Phase 3 canonical normalization across registry sources."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from contract_sweeper.normalization import run_normalization
from contract_sweeper.runtime import load_runtime_config, load_schema_registry, load_source_registry


def main() -> int:
    parser = argparse.ArgumentParser(description="Run canonical contracts normalization layer")
    parser.add_argument(
        "--sources",
        help="Comma-separated source ids. Default: all enabled sources.",
    )
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parent.parent
    runtime_config = load_runtime_config(project_root=project_root)

    source_registry = load_source_registry(runtime_config.configs_dir / "source_registry.yaml")
    schema_registry = load_schema_registry(runtime_config.configs_dir / "schema_registry.yaml")

    include_ids = None
    if args.sources:
        include_ids = {chunk.strip() for chunk in args.sources.split(",") if chunk.strip()}

    summary = run_normalization(
        project_root=project_root,
        source_registry=source_registry,
        schema_registry=schema_registry,
        include_source_ids=include_ids,
    )

    print(f"contracts_master.csv: {summary.contracts_master_csv}")
    print(f"contracts_master.parquet: {summary.contracts_master_parquet}")
    print(f"rows: {summary.total_rows}")

    for item in summary.sources:
        print(f"{item.source_id}: status={item.status} rows_in={item.rows_in} rows_out={item.rows_out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
