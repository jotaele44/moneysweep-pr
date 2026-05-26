"""On-demand geographic query function for the 82 source wirings.

This module is the on-demand counterpart to the bulk producer pipeline.
A caller passes a :class:`Query` describing the geographic + financial
slice they want; the dispatcher routes to per-source adapters, fetches
only the requested slice from upstream APIs, applies the shared
post-ingest enrichment (canonical PR-municipality geo columns), and
caches the processed result so repeat queries don't re-fetch.

Pause-lock bypass
-----------------
This module imports nothing from `contract_sweeper.pipeline.*` and writes
only under `data/cache/`. The R4.9Z source-recovery freeze (which guards
`data/staging/processed/` and the manual_import_dropzone) is out of scope
for on-demand queries by construction.
"""
from __future__ import annotations

from .cli import main
from .dispatcher import query
from .types import (
    CredentialMissing,
    ManualOnlyError,
    Query,
    QueryError,
    QueryResult,
    SourceQueryOutcome,
)

__all__ = [
    "query",
    "main",
    "Query",
    "QueryResult",
    "SourceQueryOutcome",
    "QueryError",
    "ManualOnlyError",
    "CredentialMissing",
]
