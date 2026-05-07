"""High-level runner to execute standardized ingestion sources from registry."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from .config import RuntimeConfig
from .ingestion_engine import IngestionEngine, IngestionRunResult
from .ingestion_interface import IngestionContext, PaginationPolicy, RetryPolicy
from .script_source import ScriptModuleSource
from .source_registry import SourceDefinition, SourceRegistry


@dataclass(frozen=True)
class SourceExecutionPlan:
    """Source execution plan item."""

    source_id: str
    priority: int


def build_execution_plan(registry: SourceRegistry, include_ids: set[str] | None = None) -> list[SourceExecutionPlan]:
    """Create priority-sorted source plan from registry."""

    plans = [
        SourceExecutionPlan(source_id=source.source_id, priority=source.priority)
        for source in registry.sources
        if source.enabled and (include_ids is None or source.source_id in include_ids)
    ]
    return sorted(plans, key=lambda item: item.priority)


def _get_source_definitions(registry: SourceRegistry, ids: Iterable[str]) -> list[SourceDefinition]:
    index = {source.source_id: source for source in registry.sources}
    return [index[source_id] for source_id in ids if source_id in index]


def run_sources(
    registry: SourceRegistry,
    runtime_config: RuntimeConfig,
    project_root: Path,
    include_ids: set[str] | None = None,
) -> list[IngestionRunResult]:
    """Run enabled sources using the standardized ingestion engine."""

    plan = build_execution_plan(registry, include_ids=include_ids)
    source_defs = _get_source_definitions(registry, [item.source_id for item in plan])

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    engine = IngestionEngine()
    results: list[IngestionRunResult] = []
    retry_defaults = registry.defaults.get("retry", {})
    pagination_defaults = registry.defaults.get("pagination", {})

    for source_def in source_defs:
        source = ScriptModuleSource(source_def)
        source_manifest_dir = runtime_config.manifests_dir / source_def.source_id
        context = IngestionContext(
            source_id=source_def.source_id,
            run_id=run_id,
            output_dir=runtime_config.manifests_dir,
            project_root=project_root,
            manifest_dir=source_manifest_dir,
            cache_dir=runtime_config.cache_dir,
            retry_policy=RetryPolicy(
                max_attempts=int(retry_defaults.get("max_attempts", 5)),
                base_backoff_seconds=float(retry_defaults.get("base_backoff_seconds", 1.0)),
                max_backoff_seconds=float(retry_defaults.get("max_backoff_seconds", 30.0)),
            ),
            pagination_policy=PaginationPolicy(
                mode=str(pagination_defaults.get("mode", "none")),
                page_size=int(pagination_defaults.get("page_size", 1000)),
            ),
        )
        result = engine.run_source(source, context)
        results.append(result)

    return results
