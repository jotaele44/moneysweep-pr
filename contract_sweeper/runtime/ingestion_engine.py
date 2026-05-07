"""Execution engine for standardized ingestion sources."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import time
from typing import Any

from .ingestion_interface import IngestionContext, IngestionSource


@dataclass(frozen=True)
class IngestionRunResult:
    """Result payload for a source ingestion run."""

    source_id: str
    status: str
    row_count: int
    retries: int
    manifest_path: Path
    error: str | None
    completeness: dict[str, float]


class IngestionEngine:
    """Run ingestion sources with retry/backoff and resume checkpoints."""

    def _checkpoint_path(self, context: IngestionContext) -> Path:
        state_dir = context.state_dir or (context.output_dir / "_state")
        state_dir.mkdir(parents=True, exist_ok=True)
        return state_dir / f"{context.source_id}.json"

    def _backoff(self, context: IngestionContext, attempt_idx: int) -> float:
        base = context.retry_policy.base_backoff_seconds
        cap = context.retry_policy.max_backoff_seconds
        return min(cap, base * (2 ** attempt_idx))

    def _write_checkpoint(self, path: Path, payload: dict[str, Any]) -> None:
        path.write_text(json.dumps(payload, sort_keys=True, indent=2), encoding="utf-8")

    def run_source(self, source: IngestionSource, context: IngestionContext) -> IngestionRunResult:
        """Execute one source and always emit a manifest, even on failures."""

        start = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        checkpoint = self._checkpoint_path(context)

        if context.resume_enabled and checkpoint.exists():
            context = context.with_resume_token(checkpoint.name)

        last_error: Exception | None = None
        retries = 0

        for attempt in range(context.retry_policy.max_attempts):
            try:
                raw_rows = source.fetch(context)
                normalized_rows = source.normalize_raw(raw_rows)
                validation = source.validate_raw(normalized_rows)
                completeness = source.log_completeness(context, normalized_rows)

                metadata = {
                    "ok": bool(validation.get("ok", True)),
                    "attempt": attempt + 1,
                    "retries": retries,
                    "row_count": len(normalized_rows),
                    "validation": validation,
                    "completeness": completeness,
                    "resume_token": context.resume_token,
                    "started_at": start,
                    "ended_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                }
                manifest_path = source.write_manifest(context, metadata)
                if checkpoint.exists():
                    checkpoint.unlink()

                return IngestionRunResult(
                    source_id=context.source_id,
                    status="OK" if metadata["ok"] else "WARN",
                    row_count=len(normalized_rows),
                    retries=retries,
                    manifest_path=manifest_path,
                    error=None,
                    completeness=completeness,
                )
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                retries += 1
                self._write_checkpoint(
                    checkpoint,
                    {
                        "source_id": context.source_id,
                        "attempt": attempt + 1,
                        "error": str(exc),
                        "timestamp": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                    },
                )
                if attempt + 1 >= context.retry_policy.max_attempts:
                    break
                time.sleep(self._backoff(context, attempt))

        error_msg = str(last_error) if last_error else "unknown error"
        failure_metadata = {
            "ok": False,
            "attempt": context.retry_policy.max_attempts,
            "retries": retries,
            "row_count": 0,
            "validation": {"ok": False, "error": error_msg},
            "completeness": {},
            "resume_token": context.resume_token,
            "started_at": start,
            "ended_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "error": error_msg,
        }
        manifest_path = source.write_manifest(context, failure_metadata)

        return IngestionRunResult(
            source_id=context.source_id,
            status="FAILED",
            row_count=0,
            retries=retries,
            manifest_path=manifest_path,
            error=error_msg,
            completeness={},
        )
