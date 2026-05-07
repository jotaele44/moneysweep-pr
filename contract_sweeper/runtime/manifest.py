"""Shared ingestion manifest utilities."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any


@dataclass
class IngestionManifest:
    """Common manifest shape used by all source fetchers."""

    source_id: str
    run_id: str
    status: str
    started_at: str
    ended_at: str
    page_count: int = 0
    row_count: int = 0
    field_completeness: dict[str, float] = field(default_factory=dict)
    cache_hits: int = 0
    retries: int = 0
    resume_token: str | None = None
    notes: list[str] = field(default_factory=list)

    @staticmethod
    def now_iso() -> str:
        return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def write_manifest(manifest: IngestionManifest, output_path: Path) -> Path:
    """Write a manifest JSON file in a deterministic format."""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = asdict(manifest)
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return output_path
