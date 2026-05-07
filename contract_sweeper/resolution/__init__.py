"""Entity resolution layer for Phase 4."""

from .entity_resolution import ResolutionResult, resolve_entities
from .resolution_runner import run_entity_resolution

__all__ = [
    "ResolutionResult",
    "resolve_entities",
    "run_entity_resolution",
]
