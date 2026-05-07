"""File-backed cache primitives for source fetchers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class CacheEntry:
    """Typed cache entry object."""

    key: str
    stored_at: str
    payload: dict[str, Any]


class FileCache:
    """Small JSON file cache with optional TTL validation."""

    def __init__(self, root: Path, namespace: str = "default") -> None:
        self.root = root / namespace
        self.root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _hash_key(key: str) -> str:
        return hashlib.sha256(key.encode("utf-8")).hexdigest()

    def _path_for_key(self, key: str) -> Path:
        return self.root / f"{self._hash_key(key)}.json"

    def set(self, key: str, payload: dict[str, Any]) -> Path:
        record = CacheEntry(
            key=key,
            stored_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            payload=payload,
        )
        out = self._path_for_key(key)
        out.write_text(json.dumps(record.__dict__, sort_keys=True), encoding="utf-8")
        return out

    def get(self, key: str) -> CacheEntry | None:
        path = self._path_for_key(key)
        if not path.exists():
            return None
        raw = json.loads(path.read_text(encoding="utf-8"))
        return CacheEntry(
            key=str(raw.get("key", key)),
            stored_at=str(raw.get("stored_at", "")),
            payload=dict(raw.get("payload", {})),
        )

    def get_if_fresh(self, key: str, ttl_seconds: int) -> CacheEntry | None:
        entry = self.get(key)
        if entry is None:
            return None
        try:
            created = datetime.fromisoformat(entry.stored_at.replace("Z", "+00:00"))
        except ValueError:
            return None
        age = datetime.now(timezone.utc) - created.astimezone(timezone.utc)
        if age.total_seconds() > ttl_seconds:
            return None
        return entry
