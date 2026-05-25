"""File-backed cache for on-demand query results.

Layout (under repo root, gitignored):

    data/cache/<source_id>/<query_hash>.parquet
    data/cache/<source_id>/<query_hash>.manifest.json

The sidecar manifest carries `fetched_at` (UTC ISO), `ttl_seconds`, the
canonical query dict, the row count, and the sha256 of the parquet body.
`get()` honors the manifest's TTL — expired entries are reported as misses.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from contract_sweeper.runtime.file_hash_runtime import sha256_file

from .types import Query

# update_cadence → TTL in seconds.
_DAY = 86_400
CADENCE_TTL: dict[str, int] = {
    "daily": _DAY,
    "weekly": 7 * _DAY,
    "monthly": 30 * _DAY,
    "quarterly": 90 * _DAY,
    "yearly": 365 * _DAY,
    "annual": 365 * _DAY,
}
DEFAULT_TTL = 7 * _DAY


def ttl_for_cadence(cadence: str | None) -> int:
    if not cadence:
        return DEFAULT_TTL
    return CADENCE_TTL.get(str(cadence).strip().lower(), DEFAULT_TTL)


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value)


class FileCache:
    """Read/write cache for parquet bodies with JSON sidecar manifests."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.cache_root = self.root / "data" / "cache"

    def _paths(self, source_id: str, query_hash: str) -> tuple[Path, Path]:
        dirp = self.cache_root / source_id
        body = dirp / f"{query_hash}.parquet"
        manifest = dirp / f"{query_hash}.manifest.json"
        return body, manifest

    def get(
        self,
        source_id: str,
        query_hash: str,
        *,
        ttl_seconds: int,
    ) -> tuple[pd.DataFrame, dict] | None:
        body, manifest = self._paths(source_id, query_hash)
        if not (body.exists() and manifest.exists()):
            return None
        try:
            meta = json.loads(manifest.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None
        fetched_at = meta.get("fetched_at")
        if not fetched_at:
            return None
        try:
            age = (datetime.now(timezone.utc) - _parse_iso(fetched_at)).total_seconds()
        except ValueError:
            return None
        if age > ttl_seconds:
            return None
        try:
            df = pd.read_parquet(body)
        except Exception:  # noqa: BLE001 — corrupt cache is a miss, not a crash
            return None
        return df, meta

    def put(
        self,
        source_id: str,
        query_hash: str,
        df: pd.DataFrame,
        *,
        query: Query,
        ttl_seconds: int,
    ) -> Path:
        body, manifest = self._paths(source_id, query_hash)
        body.parent.mkdir(parents=True, exist_ok=True)
        # Atomic write: tmp → rename for the parquet body. Manifest is written
        # after the body is in place so a partially-written cache entry is
        # transparently treated as a miss (no manifest).
        tmp_body = body.with_suffix(body.suffix + ".tmp")
        # Coerce object dtypes to strings to keep parquet writes portable.
        df_safe = df.copy()
        for col in df_safe.columns:
            if df_safe[col].dtype == "object":
                df_safe[col] = df_safe[col].astype(str)
        df_safe.to_parquet(tmp_body, index=False)
        tmp_body.replace(body)

        meta = {
            "source_id": source_id,
            "query_hash": query_hash,
            "query": query.canonical_dict(),
            "fetched_at": _utcnow_iso(),
            "ttl_seconds": ttl_seconds,
            "row_count": int(len(df_safe)),
            "column_count": int(len(df_safe.columns)),
            "sha256": sha256_file(body),
        }
        manifest.write_text(json.dumps(meta, indent=2, sort_keys=True), encoding="utf-8")
        return body
