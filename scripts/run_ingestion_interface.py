"""Run standardized ingestion sources defined in configs/source_registry.yaml."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from contract_sweeper.runtime import configure_logging, load_runtime_config, load_source_registry, run_sources


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Phase 2 standardized ingestion interface")
    parser.add_argument(
        "--sources",
        help="Comma-separated source ids. Default: all enabled sources in registry",
    )
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parent.parent
    runtime_config = load_runtime_config(project_root=project_root)
    logger = configure_logging(runtime_config.log_level, logger_name="contract_sweeper.ingestion")

    registry_path = runtime_config.configs_dir / "source_registry.yaml"
    registry = load_source_registry(registry_path)

    include_ids = None
    if args.sources:
        include_ids = {part.strip() for part in args.sources.split(",") if part.strip()}

    results = run_sources(
        registry=registry,
        runtime_config=runtime_config,
        project_root=project_root,
        include_ids=include_ids,
    )

    failures = [result for result in results if result.status == "FAILED"]
    for result in results:
        logger.info(
            "source=%s status=%s rows=%d retries=%d manifest=%s",
            result.source_id,
            result.status,
            result.row_count,
            result.retries,
            result.manifest_path,
        )

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
