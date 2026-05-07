"""Runtime foundation for Contract Sweeper phases 1-2."""

from .cache import FileCache
from .config import RuntimeConfig, load_runtime_config
from .ingestion_engine import IngestionEngine, IngestionRunResult
from .ingestion_interface import IngestionContext, IngestionSource
from .logging import configure_logging
from .manifest import IngestionManifest, write_manifest
from .run_ingestion import build_execution_plan, run_sources
from .schema_registry import SchemaDefinition, SchemaRegistry, load_schema_registry
from .script_source import ScriptModuleSource
from .source_registry import SourceDefinition, SourceRegistry, load_source_registry

__all__ = [
    "FileCache",
    "IngestionEngine",
    "IngestionContext",
    "IngestionManifest",
    "IngestionRunResult",
    "IngestionSource",
    "RuntimeConfig",
    "SchemaDefinition",
    "SchemaRegistry",
    "ScriptModuleSource",
    "SourceDefinition",
    "SourceRegistry",
    "build_execution_plan",
    "configure_logging",
    "load_runtime_config",
    "load_schema_registry",
    "load_source_registry",
    "run_sources",
    "write_manifest",
]
