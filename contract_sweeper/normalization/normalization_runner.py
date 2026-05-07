"""Normalization runner for canonical contracts outputs."""

from __future__ import annotations

import csv
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

import pandas as pd

from contract_sweeper.runtime.schema_registry import SchemaRegistry
from contract_sweeper.runtime.source_registry import SourceRegistry
from contract_sweeper.runtime.validation import validate_required_fields

from .canonical_contracts import CANONICAL_CONTRACT_FIELDS, OPTIONAL_CANONICAL_FIELDS
from .source_normalizer import SourceContractsNormalizer


@dataclass(frozen=True)
class SourceNormalizationSummary:
    """Normalization summary for one source."""

    source_id: str
    rows_in: int
    rows_out: int
    status: str
    output_path: Path
    completeness: dict[str, float]
    missing_required_fields: list[str]


@dataclass(frozen=True)
class NormalizationRunSummary:
    """Normalization summary for all sources."""

    sources: list[SourceNormalizationSummary]
    contracts_master_csv: Path
    contracts_master_parquet: Path
    total_rows: int


def _read_csv_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists() or path.suffix.lower() != ".csv":
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return [dict(row) for row in reader]


def _canonical_required_fields(schema_registry: SchemaRegistry) -> list[str]:
    for dataset in schema_registry.datasets:
        if dataset.name == "contracts_master":
            return dataset.required_fields
    return CANONICAL_CONTRACT_FIELDS


def _ensure_output_frame(rows: list[dict[str, Any]]) -> pd.DataFrame:
    frame = pd.DataFrame(rows)
    for col in CANONICAL_CONTRACT_FIELDS + OPTIONAL_CANONICAL_FIELDS:
        if col not in frame.columns:
            frame[col] = ""
    return frame[CANONICAL_CONTRACT_FIELDS + OPTIONAL_CANONICAL_FIELDS]


def run_normalization(
    project_root: Path,
    source_registry: SourceRegistry,
    schema_registry: SchemaRegistry,
    include_source_ids: set[str] | None = None,
) -> NormalizationRunSummary:
    """Normalize source outputs into canonical contracts schema."""

    normalized_dir = project_root / "data" / "staging" / "normalized"
    processed_dir = project_root / "data" / "staging" / "processed"
    reports_dir = project_root / "data" / "reports"

    normalized_dir.mkdir(parents=True, exist_ok=True)
    processed_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)

    required_fields = _canonical_required_fields(schema_registry)
    source_summaries: list[SourceNormalizationSummary] = []
    all_rows: list[dict[str, Any]] = []

    for source in sorted(source_registry.sources, key=lambda src: src.priority):
        if not source.enabled:
            continue
        if include_source_ids is not None and source.source_id not in include_source_ids:
            continue

        source_rows: list[dict[str, Any]] = []
        for rel_path in source.output_paths:
            source_rows.extend(_read_csv_rows(project_root / rel_path))

        normalizer = SourceContractsNormalizer(source.source_id)
        normalized_rows = normalizer.normalize_records(source_rows)
        validation = validate_required_fields(normalized_rows, required_fields)

        output_frame = _ensure_output_frame(normalized_rows)
        output_path = normalized_dir / f"{source.source_id}_normalized.csv"
        output_frame.to_csv(output_path, index=False, encoding="utf-8")

        status = "OK" if validation.ok else ("WARN" if normalized_rows else "SKIPPED")
        summary = SourceNormalizationSummary(
            source_id=source.source_id,
            rows_in=len(source_rows),
            rows_out=len(normalized_rows),
            status=status,
            output_path=output_path,
            completeness=validation.completeness,
            missing_required_fields=validation.missing_fields,
        )
        source_summaries.append(summary)
        all_rows.extend(normalized_rows)

    contracts_frame = _ensure_output_frame(all_rows)
    contracts_master_csv = processed_dir / "contracts_master.csv"
    contracts_master_parquet = processed_dir / "contracts_master.parquet"

    contracts_frame.to_csv(contracts_master_csv, index=False, encoding="utf-8")
    contracts_frame.to_parquet(contracts_master_parquet, index=False)

    report_payload = {
        "total_rows": len(contracts_frame),
        "sources": [
            {
                "source_id": item.source_id,
                "rows_in": item.rows_in,
                "rows_out": item.rows_out,
                "status": item.status,
                "output_path": str(item.output_path),
                "missing_required_fields": item.missing_required_fields,
            }
            for item in source_summaries
        ],
    }
    (reports_dir / "normalization_summary.json").write_text(
        json.dumps(report_payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    return NormalizationRunSummary(
        sources=source_summaries,
        contracts_master_csv=contracts_master_csv,
        contracts_master_parquet=contracts_master_parquet,
        total_rows=len(contracts_frame),
    )
