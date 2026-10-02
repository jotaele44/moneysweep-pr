"""Deterministic source-output ingestion into the MoneySweep source database.

Producer scripts intentionally write source-specific files.  This module is the
single boundary that turns those files into database contributions while
preserving source identity, file hashes, and row-level provenance.  Imports are
idempotent: rerunning a producer replaces the rows for that source/output
manifestation in one transaction.
"""

from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

DATABASE_RELATIVE_PATH = "data/moneysweep_sources.sqlite3"
SUPPORTED_SUFFIXES = {".csv", ".json", ".jsonl"}


def database_path(root: Path) -> Path:
    return root / DATABASE_RELATIVE_PATH


def _within(root: Path, path: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _iter_files(root: Path, expected: str) -> list[Path]:
    path = root / expected
    if not _within(root, path):
        return []
    if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES:
        return [path]
    if path.is_dir():
        return sorted(
            item
            for item in path.rglob("*")
            if item.is_file()
            and item.suffix.lower() in SUPPORTED_SUFFIXES
            and _within(root, item)
        )
    return []


def _rows(path: Path) -> Iterable[dict[str, Any]]:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        with path.open(newline="", encoding="utf-8-sig") as handle:
            yield from csv.DictReader(handle)
        return
    with path.open(encoding="utf-8") as handle:
        if suffix == ".jsonl":
            for line in handle:
                if line.strip():
                    value = json.loads(line)
                    yield value if isinstance(value, dict) else {"value": value}
            return
        value = json.load(handle)
        if isinstance(value, list):
            for item in value:
                yield item if isinstance(item, dict) else {"value": item}
        elif isinstance(value, dict):
            rows = value.get("records") or value.get("rows")
            if isinstance(rows, list):
                for item in rows:
                    yield item if isinstance(item, dict) else {"value": item}
            else:
                yield value


def _connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA foreign_keys = ON")
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS source_registry (
            source_id TEXT PRIMARY KEY,
            required INTEGER NOT NULL,
            family TEXT NOT NULL,
            expected_outputs_json TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS source_runs (
            run_id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id TEXT NOT NULL,
            status TEXT NOT NULL,
            file_count INTEGER NOT NULL,
            row_count INTEGER NOT NULL,
            error TEXT NOT NULL DEFAULT '',
            started_at TEXT NOT NULL,
            finished_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS financial_records (
            source_id TEXT NOT NULL,
            source_record_id TEXT NOT NULL,
            manifestation_path TEXT NOT NULL,
            manifestation_sha256 TEXT NOT NULL,
            row_number INTEGER NOT NULL,
            payload_json TEXT NOT NULL,
            imported_at TEXT NOT NULL,
            PRIMARY KEY (source_id, source_record_id)
        );
        CREATE INDEX IF NOT EXISTS ix_financial_records_source
            ON financial_records(source_id);
        """
    )
    return connection


def materialize_source(root: Path, source: dict[str, Any]) -> dict[str, Any]:
    """Import all currently available expected outputs for one registry source."""
    root = root.expanduser().resolve()
    source_id = str(source["source_id"])
    started = datetime.now(timezone.utc).isoformat()
    files = [
        path
        for expected in source.get("expected_outputs", [])
        for path in _iter_files(root, str(expected))
    ]
    connection = _connect(database_path(root))
    row_count = 0
    status = "NO_DATA"
    error = ""
    try:
        with connection:
            connection.execute(
                """
                INSERT INTO source_registry
                    (source_id, required, family, expected_outputs_json, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(source_id) DO UPDATE SET
                    required=excluded.required,
                    family=excluded.family,
                    expected_outputs_json=excluded.expected_outputs_json,
                    updated_at=excluded.updated_at
                """,
                (
                    source_id,
                    int(bool(source.get("required"))),
                    str(source.get("family") or ""),
                    json.dumps(source.get("expected_outputs", []), sort_keys=True),
                    started,
                ),
            )
            connection.execute("DELETE FROM financial_records WHERE source_id=?", (source_id,))
            for path in files:
                digest = _sha256(path)
                for row_number, payload in enumerate(_rows(path), start=1):
                    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
                    source_record_id = str(
                        payload.get("source_record_id")
                        or payload.get("record_id")
                        or payload.get("award_id")
                        or f"{path.relative_to(root)}:{row_number}"
                    )
                    connection.execute(
                        """
                        INSERT OR REPLACE INTO financial_records
                            (source_id, source_record_id, manifestation_path,
                             manifestation_sha256, row_number, payload_json, imported_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            source_id,
                            f"{path.relative_to(root)}:{source_record_id}",
                            str(path.relative_to(root)),
                            digest,
                            row_number,
                            encoded,
                            started,
                        ),
                    )
                    row_count += 1
            status = "IMPORTED" if row_count else "NO_DATA"
            finished = datetime.now(timezone.utc).isoformat()
            connection.execute(
                """
                INSERT INTO source_runs
                    (source_id, status, file_count, row_count, error, started_at, finished_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (source_id, status, len(files), row_count, "", started, finished),
            )
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        error = f"{type(exc).__name__}: {exc}"
        connection.rollback()
        finished = datetime.now(timezone.utc).isoformat()
        connection.execute(
            """
            INSERT INTO source_runs
                (source_id, status, file_count, row_count, error, started_at, finished_at)
            VALUES (?, 'ERROR', ?, 0, ?, ?, ?)
            """,
            (source_id, len(files), error, started, finished),
        )
        connection.commit()
        status = "ERROR"
    finally:
        connection.close()
    return {"source": source_id, "status": status, "files": len(files), "rows": row_count, "error": error}


def materialize_sources(root: Path, sources: list[dict[str, Any]]) -> dict[str, Any]:
    results = [materialize_source(root, source) for source in sources]
    return {
        "database": str(database_path(root)),
        "sources": results,
        "imported_sources": sum(item["status"] == "IMPORTED" for item in results),
        "no_data_sources": sum(item["status"] == "NO_DATA" for item in results),
        "error_sources": sum(item["status"] == "ERROR" for item in results),
        "rows": sum(item["rows"] for item in results),
    }
