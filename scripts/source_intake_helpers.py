"""Shared helpers for operator-delivered source intake.

This module is local-file only. It normalizes CSV/XLSX drops into deterministic
canonical CSV outputs while preserving row-level provenance.
"""

from __future__ import annotations

import csv
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import pandas as pd

SUPPORTED_TABULAR_SUFFIXES = {".csv", ".xlsx", ".xls"}

_SPACE_RE = re.compile(r"\s+")
_STRIP_RE = re.compile(r"[^\w\s]")
_NAME_SUFFIXES = {
    "CO",
    "CORP",
    "CORPORATION",
    "CSP",
    "INC",
    "INCORPORATED",
    "LLC",
    "LLP",
    "LP",
    "LTD",
    "LIMITED",
    "PSC",
    "SE",
    "SAS",
}


@dataclass(frozen=True)
class LoadedTable:
    """One parsed table from an operator-delivered file."""

    path: Path
    frame: pd.DataFrame


def normalize_name(value: object) -> str:
    """Return a stable uppercase entity/person name key."""

    if value is None or pd.isna(value):
        return ""
    text = str(value).upper()
    text = _STRIP_RE.sub(" ", text)
    text = _SPACE_RE.sub(" ", text).strip()
    tokens = text.split()
    while tokens and tokens[-1] in _NAME_SUFFIXES:
        tokens.pop()
    return " ".join(tokens)


def safe_text(value: object, limit: int | None = None) -> str:
    """Convert a value to normalized single-line text."""

    if value is None or pd.isna(value):
        return ""
    text = _SPACE_RE.sub(" ", str(value).replace("\n", " ")).strip()
    return text[:limit] if limit else text


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def discover_tabular_files(dropzone: Path) -> list[Path]:
    if not dropzone.exists():
        return []
    return [
        path
        for path in sorted(dropzone.iterdir())
        if path.is_file()
        and path.suffix.lower() in SUPPORTED_TABULAR_SUFFIXES
        and not path.name.startswith("~")
    ]


def read_tabular_file(path: Path) -> pd.DataFrame:
    """Read CSV/XLS/XLSX using deterministic fallback behavior."""

    suffix = path.suffix.lower()
    if suffix == ".csv":
        last_error: Exception | None = None
        for encoding in ("utf-8", "utf-8-sig", "latin-1"):
            try:
                return pd.read_csv(path, dtype=str, na_filter=False, encoding=encoding)
            except UnicodeDecodeError as exc:
                last_error = exc
        raise ValueError(f"Could not decode CSV {path}") from last_error

    if suffix in {".xlsx", ".xls"}:
        xl = pd.ExcelFile(path)
        best = pd.DataFrame()
        for sheet in xl.sheet_names:
            frame = pd.read_excel(xl, sheet_name=sheet, dtype=str, na_filter=False)
            if len(frame) > len(best):
                best = frame
        return best

    raise ValueError(f"Unsupported source-intake file: {path}")


def load_tabular_dropzone(dropzone: Path) -> list[LoadedTable]:
    loaded: list[LoadedTable] = []
    for path in discover_tabular_files(dropzone):
        frame = read_tabular_file(path)
        if not frame.empty:
            loaded.append(LoadedTable(path=path, frame=frame))
    return loaded


def resolve_column(columns: Iterable[str], candidates: Iterable[str]) -> str | None:
    source_cols = list(columns)
    lower = {col.lower(): col for col in source_cols}
    for candidate in candidates:
        if candidate in source_cols:
            return candidate
        if candidate.lower() in lower:
            return lower[candidate.lower()]
    return None


def map_frame(
    frame: pd.DataFrame,
    column_map: dict[str, list[str]],
    output_columns: list[str],
    source_id: str,
    source_file: str,
    evidence_tier: str = "T2",
    confidence: str = "0.70",
) -> pd.DataFrame:
    """Map one raw table to a declared canonical column set."""

    out: dict[str, object] = {}
    for output_col in output_columns:
        candidates = column_map.get(output_col, [])
        source_col = resolve_column(frame.columns, candidates)
        out[output_col] = frame[source_col].fillna("").astype(str) if source_col else ""

    result = pd.DataFrame(out)
    for col in output_columns:
        if col not in result.columns:
            result[col] = ""

    if "source_id" in output_columns:
        result["source_id"] = source_id
    if "source_file" in output_columns:
        result["source_file"] = source_file
    if "evidence_tier" in output_columns:
        result["evidence_tier"] = evidence_tier
    if "confidence" in output_columns:
        result["confidence"] = confidence
    if "raw_text_excerpt" in output_columns:
        text_cols = [c for c in result.columns if c != "raw_text_excerpt"]
        result["raw_text_excerpt"] = result[text_cols].astype(str).agg(" | ".join, axis=1).map(
            lambda value: safe_text(value, 240)
        )
    return result[output_columns]


def ensure_required_columns(frame: pd.DataFrame, required: Iterable[str]) -> list[str]:
    return [col for col in required if col not in frame.columns]


def write_canonical_csv(frame: pd.DataFrame, path: Path, columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = frame.copy()
    for col in columns:
        if col not in ordered.columns:
            ordered[col] = ""
    ordered = ordered[columns]
    ordered.to_csv(path, index=False, encoding="utf-8", lineterminator="\n", quoting=csv.QUOTE_MINIMAL)


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))
