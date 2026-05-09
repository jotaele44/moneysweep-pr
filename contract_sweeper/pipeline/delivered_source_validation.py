"""Validation helpers for R4.9C external source delivery."""

from __future__ import annotations

import fnmatch
import hashlib
from pathlib import Path
from typing import Any

import pandas as pd

FORBIDDEN_ARTIFACT_TOKENS = (
    "report",
    "summary",
    "graph",
    "network",
    "top_nodes",
    "top_node",
    "power_network",
    "dominance",
    "risk_alert",
    "investigative",
)

APPROVED_PREFIXES = (
    "data/staging/processed/",
    "data/staging/expansion/",
    "data/manual_import_dropzone/",
)


def contains_forbidden_token(text: str) -> bool:
    lowered = str(text or "").lower()
    return any(token in lowered for token in FORBIDDEN_ARTIFACT_TOKENS)


def split_pipe(raw: Any) -> list[str]:
    return [piece.strip() for piece in str(raw or "").split("|") if piece.strip()]


def resolve_abs(root: Path, path_value: str) -> Path:
    candidate = Path(str(path_value or "").strip())
    if candidate.is_absolute():
        return candidate
    return (root / candidate).resolve()


def relative_posix(root: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")
    except Exception:
        return ""


def is_approved_path(root: Path, path: Path) -> bool:
    rel = relative_posix(root, path)
    return bool(rel and any(rel.startswith(prefix) for prefix in APPROVED_PREFIXES))


def sha256(path: Path) -> str:
    if not path.exists() or not path.is_file():
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def row_count(path: Path) -> int:
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


def read_columns(path: Path) -> set[str]:
    if not path.exists() or not path.is_file():
        return set()
    suffix = path.suffix.lower()
    try:
        if suffix == ".csv":
            frame = pd.read_csv(path, dtype=str, low_memory=False, nrows=0)
            return {str(col) for col in frame.columns}
        if suffix == ".parquet":
            frame = pd.read_parquet(path)
            return {str(col) for col in frame.columns}
    except Exception:
        return set()
    return set()


def dedupe_paths(paths: list[Path]) -> list[Path]:
    out: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        key = str(path.resolve())
        if key in seen:
            continue
        seen.add(key)
        out.append(path)
    return out


def discover_candidate_paths(root: Path, request: dict[str, Any]) -> list[Path]:
    target_output_path = str(request.get("target_output_path", "")).strip()
    source_file = str(request.get("source_file", "")).strip()
    manifest_path = str(request.get("manifest_path", "")).strip()
    target_dropzone_path = str(request.get("target_dropzone_path", "")).strip()

    candidates: list[Path] = []

    for raw in (target_output_path, source_file):
        if raw:
            candidates.append(resolve_abs(root, raw))

    if manifest_path:
        manifest_abs = resolve_abs(root, manifest_path)
        manifest_dir = manifest_abs.parent
        for raw in (target_output_path, source_file):
            if raw:
                candidates.append((manifest_dir / Path(raw).name).resolve())

    if target_dropzone_path:
        dropzone_abs = resolve_abs(root, target_dropzone_path)
        if dropzone_abs.is_file():
            candidates.append(dropzone_abs)
        elif dropzone_abs.is_dir():
            candidates.extend(sorted(path.resolve() for path in dropzone_abs.rglob("*") if path.is_file()))

    dropzone_root = root / "data" / "manual_import_dropzone"
    processed_root = root / "data" / "staging" / "processed"
    for basename in {Path(target_output_path).name, Path(source_file).name}:
        if not basename:
            continue
        if dropzone_root.exists():
            candidates.extend(sorted(path.resolve() for path in dropzone_root.rglob(basename) if path.is_file()))
        if processed_root.exists():
            candidates.extend(sorted(path.resolve() for path in processed_root.rglob(basename) if path.is_file()))

    return [path for path in dedupe_paths(candidates) if path.exists() and path.is_file()]


def validate_candidate(
    *,
    root: Path,
    candidate: Path,
    expected_sha256: str,
    accepted_filename_patterns: str,
    required_columns: str,
) -> tuple[bool, dict[str, Any], str]:
    if not candidate.exists() or not candidate.is_file():
        return False, {}, "candidate_missing"

    if contains_forbidden_token(str(candidate)):
        return False, {}, "candidate_forbidden_artifact_path"

    if not is_approved_path(root, candidate):
        return False, {}, "candidate_not_in_approved_location"

    patterns = split_pipe(accepted_filename_patterns)
    if patterns and not any(fnmatch.fnmatch(candidate.name, pattern) for pattern in patterns):
        return False, {}, "candidate_filename_pattern_mismatch"

    rows = row_count(candidate)
    if rows <= 0:
        return False, {}, "candidate_empty_rows"

    cols_required = split_pipe(required_columns)
    cols_actual = read_columns(candidate)
    missing_cols = [col for col in cols_required if col and col not in cols_actual]
    if missing_cols:
        return False, {"missing_columns": "|".join(missing_cols)}, "candidate_missing_required_columns"

    candidate_sha = sha256(candidate)
    expected_sha = str(expected_sha256 or "").strip().lower()
    if expected_sha and candidate_sha.lower() != expected_sha:
        return False, {"candidate_sha256": candidate_sha}, "candidate_hash_mismatch"

    return (
        True,
        {
            "candidate_sha256": candidate_sha,
            "candidate_row_count": rows,
            "candidate_columns_count": len(cols_actual),
        },
        "",
    )
