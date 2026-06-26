"""R5 runtime: source/schema registries, manifest writers, validation gates.

This package is the registry-driven foundation of the Contract-Cradle
ecosystem reconstruction. It deliberately depends only on the Python
standard library so it works in CI without optional extras.

Optional features that need extra deps:
  - YAML editing of registries: pip install PyYAML (then run scripts/regenerate_registry_json.py)
  - networkx graph exports: pip install networkx (loaded lazily in builders)

Stable wire format for registries is JSON under `registries/*.json`.
"""

from moneysweep.runtime.file_hash_runtime import sha256_file
from moneysweep.runtime.name_normalization import normalize_name
from moneysweep.runtime.linkage_confidence import score_subaward_link
from moneysweep.runtime.source_registry import (
    load_source_registry,
    required_sources,
    expected_outputs_for,
)
from moneysweep.runtime.schema_registry import (
    load_schema_registry,
    canonical_columns_for,
)

__all__ = [
    "sha256_file",
    "normalize_name",
    "score_subaward_link",
    "load_source_registry",
    "required_sources",
    "expected_outputs_for",
    "load_schema_registry",
    "canonical_columns_for",
]
