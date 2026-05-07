"""Source registry loader and validator."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

REQUIRED_SUPPORT_KEYS = (
    "pagination",
    "retry_backoff",
    "resume",
    "cache",
    "time_window_splitting",
    "manifest",
    "completeness_logging",
)


@dataclass(frozen=True)
class SourceDefinition:
    """Definition for a data source in the shared source registry."""

    source_id: str
    enabled: bool
    priority: int
    module: str
    entrypoint: str
    description: str
    output_paths: list[str]
    required_fields: list[str]
    supports: dict[str, Any]


@dataclass(frozen=True)
class SourceRegistry:
    """Typed source registry object."""

    version: int
    defaults: dict[str, Any]
    sources: list[SourceDefinition]


class SourceRegistryError(ValueError):
    """Raised when source registry structure is invalid."""


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise SourceRegistryError(f"Source registry file not found: {path}")
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SourceRegistryError("Source registry root must be a mapping")
    return payload


def load_source_registry(path: Path) -> SourceRegistry:
    """Load and validate a source registry YAML file."""

    raw = _read_yaml(path)
    version = raw.get("version", 1)
    if not isinstance(version, int):
        raise SourceRegistryError("source_registry.version must be an integer")

    defaults = raw.get("defaults", {})
    if not isinstance(defaults, dict):
        raise SourceRegistryError("source_registry.defaults must be a mapping")

    raw_sources = raw.get("sources", [])
    if not isinstance(raw_sources, list):
        raise SourceRegistryError("source_registry.sources must be a list")

    sources: list[SourceDefinition] = []
    for idx, item in enumerate(raw_sources):
        if not isinstance(item, dict):
            raise SourceRegistryError(f"source_registry.sources[{idx}] must be a mapping")

        source_id = str(item.get("id", "")).strip()
        module = str(item.get("module", "")).strip()
        priority = int(item.get("priority", 999))
        entrypoint = str(item.get("entrypoint", "run")).strip() or "run"
        if not source_id:
            raise SourceRegistryError(f"source_registry.sources[{idx}].id is required")
        if not module:
            raise SourceRegistryError(f"source_registry.sources[{idx}].module is required")

        supports = item.get("supports", {})
        if not isinstance(supports, dict):
            raise SourceRegistryError(f"source_registry.sources[{idx}].supports must be a mapping")

        missing_support_keys = [k for k in REQUIRED_SUPPORT_KEYS if k not in supports]
        if missing_support_keys:
            keys = ", ".join(missing_support_keys)
            raise SourceRegistryError(
                f"source_registry.sources[{idx}].supports missing required keys: {keys}"
            )

        output_paths_raw = item.get("output_paths", [])
        if not isinstance(output_paths_raw, list) or not all(isinstance(p, str) for p in output_paths_raw):
            raise SourceRegistryError(f"source_registry.sources[{idx}].output_paths must be a list of strings")

        required_fields_raw = item.get("required_fields", [])
        if not isinstance(required_fields_raw, list) or not all(isinstance(p, str) for p in required_fields_raw):
            raise SourceRegistryError(f"source_registry.sources[{idx}].required_fields must be a list of strings")

        sources.append(
            SourceDefinition(
                source_id=source_id,
                enabled=bool(item.get("enabled", True)),
                priority=priority,
                module=module,
                entrypoint=entrypoint,
                description=str(item.get("description", "")).strip(),
                output_paths=[p.strip() for p in output_paths_raw if p.strip()],
                required_fields=[p.strip() for p in required_fields_raw if p.strip()],
                supports=supports,
            )
        )

    return SourceRegistry(version=version, defaults=defaults, sources=sources)
