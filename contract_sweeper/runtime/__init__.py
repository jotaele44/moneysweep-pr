"""Runtime foundation for Contract Sweeper phases 1-2."""

from .cache import FileCache
from .config import RuntimeConfig, load_runtime_config
from .ingestion_interface import IngestionContext, IngestionSource
from .logging import configure_logging
from .manifest import IngestionManifest, write_manifest
from .schema_registry import SchemaDefinition, SchemaRegistry, load_schema_registry
from .source_registry import SourceDefinition, SourceRegistry, load_source_registry

__all__ = [
    "FileCache",
    "IngestionContext",
    "IngestionManifest",
    "IngestionSource",
    "RuntimeConfig",
    "SchemaDefinition",
    "SchemaRegistry",
    "SourceDefinition",
    "SourceRegistry",
    "configure_logging",
    "load_runtime_config",
    "load_schema_registry",
    "load_source_registry",
    "write_manifest",
]
