"""Source registry loader and validator."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class SourceDefinition:
    """Definition for a data source in the shared source registry."""

    source_id: str
    enabled: bool
    module: str
    description: str
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
        if not source_id:
            raise SourceRegistryError(f"source_registry.sources[{idx}].id is required")
        if not module:
            raise SourceRegistryError(f"source_registry.sources[{idx}].module is required")

        supports = item.get("supports", {})
        if not isinstance(supports, dict):
            raise SourceRegistryError(f"source_registry.sources[{idx}].supports must be a mapping")

        sources.append(
            SourceDefinition(
                source_id=source_id,
                enabled=bool(item.get("enabled", True)),
                module=module,
                description=str(item.get("description", "")).strip(),
                supports=supports,
            )
        )

    return SourceRegistry(version=version, defaults=defaults, sources=sources)
