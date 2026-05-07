"""Runner for Phase 4 entity resolution outputs."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

import pandas as pd

from .entity_resolution import ResolutionResult, resolve_entities


@dataclass(frozen=True)
class ResolutionRunArtifacts:
    """Filesystem outputs from entity resolution run."""

    entities_resolved_csv: Path
    alias_registry_json: Path
    low_confidence_review_queue_csv: Path
    high_value_unresolved_csv: Path
    summary_json: Path
    summary: dict[str, Any]


def _load_contracts_master(project_root: Path, input_path: Path | None = None) -> pd.DataFrame:
    if input_path is not None:
        if input_path.suffix.lower() == ".parquet":
            return pd.read_parquet(input_path)
        return pd.read_csv(input_path, dtype=str, low_memory=False)

    parquet_path = project_root / "data" / "staging" / "processed" / "contracts_master.parquet"
    csv_path = project_root / "data" / "staging" / "processed" / "contracts_master.csv"

    if parquet_path.exists():
        return pd.read_parquet(parquet_path)
    if csv_path.exists():
        return pd.read_csv(csv_path, dtype=str, low_memory=False)

    return pd.DataFrame()


def run_entity_resolution(
    project_root: Path,
    input_path: Path | None = None,
    review_threshold: float = 0.85,
    fuzzy_threshold_high: float = 93.0,
    fuzzy_threshold_medium: float = 88.0,
    high_value_threshold: float = 1_000_000.0,
) -> ResolutionRunArtifacts:
    """Run entity resolution and write Phase 4 artifacts."""

    processed_dir = project_root / "data" / "staging" / "processed"
    reports_dir = project_root / "data" / "reports"
    processed_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)

    contracts = _load_contracts_master(project_root, input_path=input_path)

    result: ResolutionResult = resolve_entities(
        contracts=contracts,
        fuzzy_threshold_high=fuzzy_threshold_high,
        fuzzy_threshold_medium=fuzzy_threshold_medium,
        review_threshold=review_threshold,
        high_value_threshold=high_value_threshold,
    )

    entities_resolved_csv = processed_dir / "entities_resolved.csv"
    alias_registry_json = processed_dir / "alias_registry.json"
    low_confidence_review_queue_csv = processed_dir / "low_confidence_review_queue.csv"
    high_value_unresolved_csv = processed_dir / "high_value_unresolved_entities.csv"
    summary_json = reports_dir / "entity_resolution_summary.json"

    result.entities_resolved.to_csv(entities_resolved_csv, index=False, encoding="utf-8")
    result.low_confidence_review_queue.to_csv(low_confidence_review_queue_csv, index=False, encoding="utf-8")
    result.high_value_unresolved_entities.to_csv(high_value_unresolved_csv, index=False, encoding="utf-8")

    alias_registry_json.write_text(
        json.dumps(result.alias_registry, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    summary_json.write_text(
        json.dumps(result.summary, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    return ResolutionRunArtifacts(
        entities_resolved_csv=entities_resolved_csv,
        alias_registry_json=alias_registry_json,
        low_confidence_review_queue_csv=low_confidence_review_queue_csv,
        high_value_unresolved_csv=high_value_unresolved_csv,
        summary_json=summary_json,
        summary=result.summary,
    )
