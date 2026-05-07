"""Schema registry loader and validator."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class SchemaDefinition:
    """Canonical schema description for a dataset."""

    name: str
    format: str
    required_fields: list[str]
    optional_fields: list[str]


@dataclass(frozen=True)
class SchemaRegistry:
    """Typed schema registry object."""

    version: int
    datasets: list[SchemaDefinition]


class SchemaRegistryError(ValueError):
    """Raised when schema registry structure is invalid."""


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise SchemaRegistryError(f"Schema registry file not found: {path}")
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SchemaRegistryError("Schema registry root must be a mapping")
    return payload


def _read_string_list(raw: Any, field_name: str) -> list[str]:
    if raw is None:
        return []
    if not isinstance(raw, list) or not all(isinstance(v, str) for v in raw):
        raise SchemaRegistryError(f"{field_name} must be a list of strings")
    return [v.strip() for v in raw if v.strip()]


def load_schema_registry(path: Path) -> SchemaRegistry:
    """Load and validate a schema registry YAML file."""

    raw = _load_yaml(path)
    version = raw.get("version", 1)
    if not isinstance(version, int):
        raise SchemaRegistryError("schema_registry.version must be an integer")

    raw_datasets = raw.get("datasets", [])
    if not isinstance(raw_datasets, list):
        raise SchemaRegistryError("schema_registry.datasets must be a list")

    datasets: list[SchemaDefinition] = []
    for idx, item in enumerate(raw_datasets):
        if not isinstance(item, dict):
            raise SchemaRegistryError(f"schema_registry.datasets[{idx}] must be a mapping")

        name = str(item.get("name", "")).strip()
        fmt = str(item.get("format", "")).strip().lower() or "csv"
        if not name:
            raise SchemaRegistryError(f"schema_registry.datasets[{idx}].name is required")

        required_fields = _read_string_list(
            item.get("required_fields", []),
            f"schema_registry.datasets[{idx}].required_fields",
        )
        optional_fields = _read_string_list(
            item.get("optional_fields", []),
            f"schema_registry.datasets[{idx}].optional_fields",
        )
        overlap = set(required_fields).intersection(optional_fields)
        if overlap:
            overlap_sorted = ", ".join(sorted(overlap))
            raise SchemaRegistryError(
                f"schema_registry.datasets[{idx}] has duplicate required/optional fields: {overlap_sorted}"
            )

        datasets.append(
            SchemaDefinition(
                name=name,
                format=fmt,
                required_fields=required_fields,
                optional_fields=optional_fields,
            )
        )

    return SchemaRegistry(version=version, datasets=datasets)
