"""Adapter that wraps legacy script modules behind the ingestion interface."""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from importlib import import_module
import inspect
from pathlib import Path
from typing import Any

from .ingestion_interface import IngestionContext, IngestionSource
from .manifest import IngestionManifest, write_manifest
from .source_registry import SourceDefinition
from .validation import validate_required_fields


@dataclass
class ScriptModuleSource(IngestionSource):
    """IngestionSource adapter for existing script-style modules."""

    definition: SourceDefinition
    _last_summary: dict[str, Any] = field(default_factory=dict)

    def _load_rows_from_outputs(self, project_root: Path) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for rel_path in self.definition.output_paths:
            path = (project_root / rel_path).resolve()
            if not path.exists() or path.suffix.lower() != ".csv":
                continue
            with path.open("r", encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle)
                for row in reader:
                    row["__source_file"] = str(path)
                    rows.append(row)
        return rows

    def fetch(self, context: IngestionContext) -> list[dict[str, Any]]:
        module = import_module(self.definition.module)
        entrypoint = getattr(module, self.definition.entrypoint)
        signature = inspect.signature(entrypoint)

        kwargs: dict[str, Any] = {}
        project_root = context.project_root or context.output_dir
        if "root" in signature.parameters:
            kwargs["root"] = project_root
        if "resume" in signature.parameters:
            kwargs["resume"] = context.resume_enabled

        summary = entrypoint(**kwargs) if kwargs else entrypoint()
        if isinstance(summary, dict):
            self._last_summary = summary

        return self._load_rows_from_outputs(project_root)

    def normalize_raw(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return rows

    def validate_raw(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        result = validate_required_fields(rows, self.definition.required_fields)
        return {
            "ok": result.ok,
            "missing_fields": result.missing_fields,
            "row_count": result.row_count,
            "completeness": result.completeness,
            "summary": self._last_summary,
        }

    def write_manifest(self, context: IngestionContext, metadata: dict[str, Any]) -> Path:
        if metadata.get("error"):
            status = "FAILED"
        elif metadata.get("ok", True):
            status = "OK"
        else:
            status = "WARN"
        manifest = IngestionManifest(
            source_id=context.source_id,
            run_id=context.run_id,
            status=status,
            started_at=str(metadata.get("started_at", IngestionManifest.now_iso())),
            ended_at=str(metadata.get("ended_at", IngestionManifest.now_iso())),
            page_count=int(self._last_summary.get("page_count", 0) or 0),
            row_count=int(metadata.get("row_count", 0) or 0),
            field_completeness=dict(metadata.get("completeness", {})),
            cache_hits=int(self._last_summary.get("cache_hits", 0) or 0),
            retries=int(metadata.get("retries", 0) or 0),
            resume_token=context.resume_token,
            notes=[f"module={self.definition.module}", f"entrypoint={self.definition.entrypoint}"],
        )

        manifest_dir = context.manifest_dir or (context.output_dir / "manifests")
        return write_manifest(manifest, manifest_dir / f"{context.source_id}.json")

    def log_completeness(self, context: IngestionContext, rows: list[dict[str, Any]]) -> dict[str, float]:
        if not rows:
            return {field: 0.0 for field in self.definition.required_fields}

        keys = self.definition.required_fields or sorted(rows[0].keys())
        metrics: dict[str, float] = {}
        row_count = len(rows)

        for key in keys:
            populated = sum(1 for row in rows if str(row.get(key, "")).strip() != "")
            metrics[key] = round(populated / row_count, 4)

        return metrics
