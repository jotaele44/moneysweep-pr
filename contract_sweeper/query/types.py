"""Public data types for the on-demand query module."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Literal

import pandas as pd

Status = Literal["ok", "cache_hit", "manual_only", "error"]


def _canonical(seq: tuple[Any, ...]) -> list:
    """Stable, deduped, sorted list for hashing."""
    return sorted({str(x) for x in seq})


@dataclass(frozen=True)
class Query:
    """Geographic + financial filter spec for the on-demand query function.

    All sequence fields are order-insensitive for hashing: the cache key
    derives from a canonical (sorted + deduped) form so callers don't have
    to normalize them manually.
    """

    municipalities: tuple[str, ...] = ()
    fiscal_years: tuple[int, ...] = ()
    date_range: tuple[str, str] | None = None
    agencies: tuple[str, ...] = ()
    recipient_ueis: tuple[str, ...] = ()

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "municipalities": _canonical(self.municipalities),
            "fiscal_years": sorted({int(y) for y in self.fiscal_years}),
            "date_range": list(self.date_range) if self.date_range else None,
            "agencies": _canonical(self.agencies),
            "recipient_ueis": _canonical(self.recipient_ueis),
        }

    def canonical_hash(self) -> str:
        payload = json.dumps(self.canonical_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


@dataclass
class SourceQueryOutcome:
    source_id: str
    status: Status
    df: pd.DataFrame | None = None
    rows: int = 0
    fetched_at: str | None = None
    error: str | None = None
    reason: str | None = None  # populated for manual_only


@dataclass
class QueryResult:
    query: Query
    outcomes: dict[str, SourceQueryOutcome] = field(default_factory=dict)

    @property
    def combined(self) -> pd.DataFrame:
        """Concatenate every ok / cache_hit result, tagging rows with source_id."""
        frames: list[pd.DataFrame] = []
        for sid, out in self.outcomes.items():
            if out.status in ("ok", "cache_hit") and out.df is not None and len(out.df) > 0:
                tagged = out.df.copy()
                tagged["source_id"] = sid
                frames.append(tagged)
        if not frames:
            return pd.DataFrame()
        return pd.concat(frames, ignore_index=True, sort=False)

    def summary(self) -> dict[str, Any]:
        return {
            "query_hash": self.query.canonical_hash(),
            "source_count": len(self.outcomes),
            "ok": sum(1 for o in self.outcomes.values() if o.status == "ok"),
            "cache_hit": sum(1 for o in self.outcomes.values() if o.status == "cache_hit"),
            "manual_only": sum(1 for o in self.outcomes.values() if o.status == "manual_only"),
            "error": sum(1 for o in self.outcomes.values() if o.status == "error"),
            "total_rows": sum(o.rows for o in self.outcomes.values()),
        }


class QueryError(Exception):
    """Base class for query module exceptions."""


class ManualOnlyError(QueryError):
    """Raised by stub adapters for sources with no on-demand path."""

    def __init__(self, source_id: str, producer_script: str | None, authentication: str | None):
        self.source_id = source_id
        self.producer_script = producer_script
        self.authentication = authentication
        super().__init__(
            f"{source_id}: no on-demand adapter; run producer "
            f"{producer_script or '(unknown)'} (auth: {authentication or 'unknown'})"
        )


class CredentialMissing(QueryError):
    """Raised when an adapter needs an env var that isn't set."""

    def __init__(self, source_id: str, env_var: str):
        self.source_id = source_id
        self.env_var = env_var
        super().__init__(f"{source_id}: required credential ${env_var} is not set")
