"""Top-level query dispatcher: routes a Query across the registered adapters."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from contract_sweeper.runtime.post_ingest import apply_post_ingest
from contract_sweeper.runtime.source_registry import (
    REPO_ROOT,
    all_sources,
    source_by_id,
)

from .adapters import (
    ADAPTER_REGISTRY,
    ENTITY_ADAPTER_REGISTRY,
    get_adapter,
    get_entity_adapter,
)
from .cache import FileCache, ttl_for_cadence
from .entity_types import EntityQuery
from .types import (
    CredentialMissing,
    ManualOnlyError,
    Query,
    QueryResult,
    SourceQueryOutcome,
)

_LOG = logging.getLogger(__name__)


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_source_ids(root: Path) -> list[str]:
    """When the caller doesn't specify sources, query every adapter we have."""
    known = set(ADAPTER_REGISTRY.keys())
    # Order by registry order so results are deterministic.
    return [s.get("source_id") for s in all_sources(root) if s.get("source_id") in known]


def _resolve_ttl(source_id: str, root: Path) -> int:
    src = source_by_id(source_id, root) or {}
    return ttl_for_cadence(src.get("update_cadence"))


def _query_one(
    source_id: str,
    criteria: Query,
    *,
    root: Path,
    cache: FileCache,
    force_refresh: bool,
) -> SourceQueryOutcome:
    query_hash = criteria.canonical_hash()
    ttl = _resolve_ttl(source_id, root)

    if not force_refresh:
        hit = cache.get(source_id, query_hash, ttl_seconds=ttl)
        if hit is not None:
            df, meta = hit
            return SourceQueryOutcome(
                source_id=source_id,
                status="cache_hit",
                df=df,
                rows=int(len(df)),
                fetched_at=meta.get("fetched_at"),
            )

    adapter = get_adapter(source_id, root=root)
    try:
        raw = adapter.fetch(criteria)
    except ManualOnlyError as exc:
        return SourceQueryOutcome(
            source_id=source_id,
            status="manual_only",
            df=None,
            rows=0,
            fetched_at=None,
            reason=str(exc),
        )
    except CredentialMissing as exc:
        return SourceQueryOutcome(
            source_id=source_id,
            status="error",
            df=None,
            rows=0,
            fetched_at=None,
            error=str(exc),
        )
    except Exception as exc:  # noqa: BLE001 — adapter errors must not bubble
        _LOG.exception("adapter %s failed", source_id)
        return SourceQueryOutcome(
            source_id=source_id,
            status="error",
            df=None,
            rows=0,
            fetched_at=None,
            error=f"{type(exc).__name__}: {exc}",
        )

    enriched = apply_post_ingest(raw, source_id=source_id, root=root)
    cache.put(source_id, query_hash, enriched, query=criteria, ttl_seconds=ttl)
    return SourceQueryOutcome(
        source_id=source_id,
        status="ok",
        df=enriched,
        rows=int(len(enriched)),
        fetched_at=_utcnow_iso(),
    )


def query(
    criteria: Query,
    *,
    source_ids: list[str] | None = None,
    root: Path | None = None,
    force_refresh: bool = False,
) -> QueryResult:
    """Run an on-demand geographic + financial query across one or more sources.

    Parameters
    ----------
    criteria
        The query spec. Sequence fields are order-insensitive for caching.
    source_ids
        Registry source_ids to consult. None defaults to every source that
        has a concrete adapter (currently usaspending_prime,
        fema_pa_openfema_v2, fec). Unknown source_ids resolve to the stub
        adapter, returning `status='manual_only'`.
    root
        Repo root. Defaults to the package's REPO_ROOT.
    force_refresh
        Skip the cache lookup and re-fetch from upstream.
    """
    root = Path(root) if root else REPO_ROOT
    cache = FileCache(root)
    if source_ids is None:
        source_ids = _default_source_ids(root)

    result = QueryResult(query=criteria)
    for sid in source_ids:
        result.outcomes[sid] = _query_one(
            sid, criteria, root=root, cache=cache, force_refresh=force_refresh
        )
    return result


def _entity_query_one(
    source_id: str,
    criteria: EntityQuery,
    *,
    root: Path,
    cache: FileCache,
    force_refresh: bool,
) -> SourceQueryOutcome:
    query_hash = criteria.canonical_hash()
    ttl = _resolve_ttl(source_id, root)

    if not force_refresh:
        hit = cache.get(source_id, query_hash, ttl_seconds=ttl)
        if hit is not None:
            df, meta = hit
            return SourceQueryOutcome(
                source_id=source_id,
                status="cache_hit",
                df=df,
                rows=int(len(df)),
                fetched_at=meta.get("fetched_at"),
            )

    if source_id not in ENTITY_ADAPTER_REGISTRY:
        return SourceQueryOutcome(
            source_id=source_id,
            status="manual_only",
            df=None,
            rows=0,
            fetched_at=None,
            reason=f"{source_id}: no entity-mode adapter registered",
        )

    adapter = get_entity_adapter(source_id, root=root)
    try:
        raw = adapter.fetch(criteria)
    except CredentialMissing as exc:
        return SourceQueryOutcome(
            source_id=source_id,
            status="error",
            df=None,
            rows=0,
            fetched_at=None,
            error=str(exc),
        )
    except Exception as exc:  # noqa: BLE001 — adapter errors must not bubble
        _LOG.exception("entity adapter %s failed", source_id)
        return SourceQueryOutcome(
            source_id=source_id,
            status="error",
            df=None,
            rows=0,
            fetched_at=None,
            error=f"{type(exc).__name__}: {exc}",
        )

    # No post_ingest for entity records: they aren't PR-row-shaped.
    cache.put(source_id, query_hash, raw, query=criteria, ttl_seconds=ttl)
    return SourceQueryOutcome(
        source_id=source_id,
        status="ok",
        df=raw,
        rows=int(len(raw)),
        fetched_at=_utcnow_iso(),
    )


def query_entities(
    criteria: EntityQuery,
    *,
    source_ids: list[str] | None = None,
    root: Path | None = None,
    force_refresh: bool = False,
) -> QueryResult:
    """Run an on-demand entity-mode query across one or more registered adapters.

    Parameters
    ----------
    criteria
        The entity-mode query spec. Identifier order doesn't affect caching.
    source_ids
        Registered entity source_ids to consult. None defaults to every
        adapter in :data:`ENTITY_ADAPTER_REGISTRY`. Unknown source_ids
        resolve to ``status='manual_only'`` outcomes.
    root
        Repo root. Defaults to the package's REPO_ROOT.
    force_refresh
        Skip the cache lookup and re-fetch from upstream.
    """
    root = Path(root) if root else REPO_ROOT
    cache = FileCache(root)
    if source_ids is None:
        source_ids = sorted(ENTITY_ADAPTER_REGISTRY.keys())

    result = QueryResult(query=criteria)
    for sid in source_ids:
        result.outcomes[sid] = _entity_query_one(
            sid, criteria, root=root, cache=cache, force_refresh=force_refresh
        )
    return result
