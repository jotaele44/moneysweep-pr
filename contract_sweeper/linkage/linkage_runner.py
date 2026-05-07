"""Runner for Phase 5 chain-linkage artifacts."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

import pandas as pd

from contract_sweeper.linkage.chain_linkage import ChainLinkageResult, build_execution_chain
from contract_sweeper.runtime.schema_registry import SchemaRegistry
from contract_sweeper.runtime.validation import validate_required_fields


@dataclass(frozen=True)
class LinkageRunArtifacts:
    """Filesystem outputs from execution chain linkage run."""

    execution_chain_master_csv: Path
    execution_chain_per_asset_csv: Path
    low_confidence_review_queue_csv: Path
    summary_json: Path
    summary: dict[str, Any]


def _load_contracts(project_root: Path, input_path: Path | None = None) -> pd.DataFrame:
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


def _load_entities_resolved(project_root: Path, path: Path | None = None) -> pd.DataFrame:
    if path is not None and path.exists():
        return pd.read_csv(path, dtype=str, low_memory=False)

    default_path = project_root / "data" / "staging" / "processed" / "entities_resolved.csv"
    if default_path.exists():
        return pd.read_csv(default_path, dtype=str, low_memory=False)
    return pd.DataFrame()


def _execution_chain_required_fields(schema_registry: SchemaRegistry) -> list[str]:
    for dataset in schema_registry.datasets:
        if dataset.name == "execution_chain_master":
            return dataset.required_fields
    return ["entity_id", "project_id", "funding_source", "source_system", "link_confidence"]


def run_chain_linkage(
    project_root: Path,
    schema_registry: SchemaRegistry,
    contracts_input_path: Path | None = None,
    entities_resolved_path: Path | None = None,
    review_threshold: float = 0.85,
    fuzzy_high: float = 93.0,
    fuzzy_medium: float = 88.0,
    linkage_target: float = 0.90,
) -> LinkageRunArtifacts:
    """Run execution chain linkage and write Phase 5 artifacts."""

    processed_dir = project_root / "data" / "staging" / "processed"
    reports_dir = project_root / "data" / "reports"
    processed_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)

    contracts = _load_contracts(project_root, input_path=contracts_input_path)
    entities_resolved = _load_entities_resolved(project_root, path=entities_resolved_path)

    result: ChainLinkageResult = build_execution_chain(
        contracts=contracts,
        resolved_entities=entities_resolved,
        fuzzy_high=fuzzy_high,
        fuzzy_medium=fuzzy_medium,
        review_threshold=review_threshold,
        linkage_target=linkage_target,
    )

    required_fields = _execution_chain_required_fields(schema_registry)
    validation = validate_required_fields(
        result.execution_chain_master.to_dict(orient="records"),
        required_fields,
    )

    execution_chain_master_csv = processed_dir / "execution_chain_master.csv"
    execution_chain_per_asset_csv = processed_dir / "execution_chain_per_asset.csv"
    low_confidence_review_queue_csv = processed_dir / "execution_chain_review_queue.csv"
    summary_json = reports_dir / "execution_chain_summary.json"

    result.execution_chain_master.to_csv(execution_chain_master_csv, index=False, encoding="utf-8")
    result.execution_chain_per_asset.to_csv(execution_chain_per_asset_csv, index=False, encoding="utf-8")
    result.low_confidence_review_queue.to_csv(low_confidence_review_queue_csv, index=False, encoding="utf-8")

    summary = {**result.summary}
    summary.update(
        {
            "schema_required_fields": required_fields,
            "schema_validation_ok": bool(validation.ok),
            "schema_missing_required_fields": validation.missing_fields,
            "schema_field_completeness": validation.completeness,
        }
    )

    summary_json.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")

    return LinkageRunArtifacts(
        execution_chain_master_csv=execution_chain_master_csv,
        execution_chain_per_asset_csv=execution_chain_per_asset_csv,
        low_confidence_review_queue_csv=low_confidence_review_queue_csv,
        summary_json=summary_json,
        summary=summary,
    )
