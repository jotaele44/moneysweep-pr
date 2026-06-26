"""Source manifest inventory writer for controlled backfill phases."""

from __future__ import annotations

import csv
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha256(path: Path) -> str:
    if not path.exists() or not path.is_file():
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _record_count(path: Path) -> int:
    if not path.exists() or not path.is_file():
        return 0

    suffix = path.suffix.lower()
    try:
        if suffix == ".csv":
            with path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
                return max(sum(1 for _ in handle) - 1, 0)
        if suffix == ".parquet":
            return int(len(pd.read_parquet(path)))
    except Exception:
        return 0
    return 0


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_source_manifest_inventory(
    root: Path,
    rows: list[dict[str, Any]],
    *,
    output_relpath: str = "data/exports/source_manifest_inventory_r4_8.csv",
) -> tuple[str, int]:
    """Write source manifest inventory CSV.

    Returns:
        (output_relpath, row_count_written)
    """

    root = Path(root)
    generated_at = _utc_now()

    out_rows: list[dict[str, Any]] = []
    for row in rows:
        source_file = str(row.get("source_file", "")).strip()
        source_abs = root / source_file if source_file else Path("/dev/null")

        out_rows.append(
            {
                "source_system": str(row.get("source_system", "")),
                "source_file": source_file,
                "source_record_count": _record_count(source_abs),
                "source_sha256": _sha256(source_abs),
                "generated_at": generated_at,
                "producer_script": str(row.get("producer_script", "")),
                "target_output_path": str(row.get("target_output_path", "")),
                "schema_version": str(row.get("schema_version", "r4_8_schema_draft")),
                "validation_status": str(row.get("validation_status", "not_validated")),
                "known_gaps": str(row.get("known_gaps", "")),
            }
        )

    output_path = root / output_relpath
    _write_csv(
        output_path,
        out_rows,
        [
            "source_system",
            "source_file",
            "source_record_count",
            "source_sha256",
            "generated_at",
            "producer_script",
            "target_output_path",
            "schema_version",
            "validation_status",
            "known_gaps",
        ],
    )

    return output_relpath, len(out_rows)
