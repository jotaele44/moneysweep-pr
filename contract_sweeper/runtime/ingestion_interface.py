"""Standard ingestion interface contract for all source fetchers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class RetryPolicy:
    """Retry/backoff controls for a source fetcher."""

    max_attempts: int = 5
    base_backoff_seconds: float = 1.0
    max_backoff_seconds: float = 30.0


@dataclass(frozen=True)
class PaginationPolicy:
    """Pagination controls for a source fetcher."""

    mode: str = "none"
    page_size: int = 1000


@dataclass(frozen=True)
class IngestionContext:
    """Shared context passed into every source implementation."""

    source_id: str
    run_id: str
    output_dir: Path
    project_root: Path | None = None
    manifest_dir: Path | None = None
    cache_dir: Path | None = None
    state_dir: Path | None = None
    cache_enabled: bool = True
    resume_enabled: bool = True
    resume_token: str | None = None
    retry_policy: RetryPolicy = RetryPolicy()
    pagination_policy: PaginationPolicy = PaginationPolicy()
    window_start: date | None = None
    window_end: date | None = None

    def with_resume_token(self, token: str | None) -> "IngestionContext":
        """Return a copy of this context with an updated resume token."""
        return replace(self, resume_token=token)


class IngestionSource(ABC):
    """Required source interface for Phase 2 standardization."""

    @abstractmethod
    def fetch(self, context: IngestionContext) -> list[dict[str, Any]]:
        """Fetch raw records with pagination/retry/resume/cache support."""

    @abstractmethod
    def normalize_raw(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Normalize raw source records into source-level normalized shape."""

    @abstractmethod
    def validate_raw(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        """Validate raw rows and return diagnostics metadata."""

    @abstractmethod
    def write_manifest(self, context: IngestionContext, metadata: dict[str, Any]) -> Path:
        """Persist source manifest describing execution and completeness."""

    @abstractmethod
    def log_completeness(self, context: IngestionContext, rows: list[dict[str, Any]]) -> dict[str, float]:
        """Log and return row-count and field-completeness statistics."""
