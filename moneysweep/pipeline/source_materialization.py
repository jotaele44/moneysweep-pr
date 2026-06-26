"""R4.9B validated source materialization helpers."""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from typing import Any

import pandas as pd

from moneysweep.pipeline.acquisition_package import (
    read_csv,
    safe_int,
    utc_now,
    write_csv,
    write_json,
)

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

VALIDATED_MANIFEST_TYPE = "validated_source_manifest"
APPROVED_STAGE_PREFIXES = (
    "data/staging/processed/",
    "data/staging/expansion/",
)


def _contains_forbidden_token(text: str) -> bool:
    lowered = str(text or "").lower()
    return any(token in lowered for token in FORBIDDEN_ARTIFACT_TOKENS)


def _status_is_validated(value: str) -> bool:
    lowered = str(value or "").strip().lower()
    if not lowered:
        return False
    if lowered.startswith("valid"):
        return True
    return lowered in {"ok", "passed", "success", VALIDATED_MANIFEST_TYPE}


def _manifest_type_valid(value: str) -> bool:
    return str(value or "").strip().lower() == VALIDATED_MANIFEST_TYPE


def _resolve_abs(root: Path, raw_path: str) -> Path:
    raw = Path(str(raw_path or "").strip())
    if raw.is_absolute():
        return raw
    return (root / raw).resolve()


def _relative_posix(root: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")
    except Exception:
        return ""


def _is_approved_stage_path(path: Path, roots: list[Path]) -> bool:
    for root in roots:
        rel = _relative_posix(root, path)
        if rel and any(rel.startswith(prefix) for prefix in APPROVED_STAGE_PREFIXES):
            return True
    return False


def _sha256(path: Path) -> str:
    if not path.exists() or not path.is_file():
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _row_count(path: Path) -> int:
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


def _dedupe_paths(paths: list[Path]) -> list[Path]:
    out: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        key = str(path.resolve())
        if key in seen:
            continue
        seen.add(key)
        out.append(path)
    return out


def _candidate_roots(root: Path) -> list[Path]:
    roots: list[Path] = [root]

    worktrees_parent = root.parent
    if worktrees_parent.exists() and worktrees_parent.is_dir():
        for candidate in sorted(worktrees_parent.iterdir()):
            if candidate.is_dir() and candidate.resolve() != root.resolve():
                roots.append(candidate)

    github_root = root.parents[2] if len(root.parents) >= 3 else None
    if github_root:
        main_repo = github_root / "moneysweep-pr"
        if main_repo.exists() and main_repo.is_dir():
            roots.append(main_repo)

    return _dedupe_paths(roots)


def _candidate_paths(
    *,
    root: Path,
    target_output_path: str,
    source_file: str,
    source_manifest_path: str,
) -> list[Path]:
    candidates: list[Path] = []
    root_candidates = _candidate_roots(root)

    target_rel = str(target_output_path or "").strip()
    source_rel = str(source_file or "").strip()

    for candidate_root in root_candidates:
        if target_rel:
            candidates.append(_resolve_abs(candidate_root, target_rel))
        if source_rel:
            candidates.append(_resolve_abs(candidate_root, source_rel))

        for rel in (target_rel, source_rel):
            if not rel:
                continue
            base = Path(rel).name
            candidates.append((candidate_root / "data" / "staging" / "processed" / base).resolve())
            candidates.append((candidate_root / "data" / "staging" / "expansion" / base).resolve())

    if source_manifest_path:
        manifest_abs = _resolve_abs(root, source_manifest_path)
        manifest_dir = manifest_abs.parent
        for rel in (target_rel, source_rel):
            if not rel:
                continue
            candidates.append((manifest_dir / Path(rel).name).resolve())

    return _dedupe_paths(candidates)


def _record_from_manifest(root: Path, row: dict[str, str]) -> dict[str, Any]:
    target_output_path = str(row.get("target_output_path", "")).strip()
    source_file = str(row.get("source_file", "")).strip()
    source_manifest_path = str(row.get("manifest_path", "")).strip()
    row_count = safe_int(row.get("row_count"))
    sha256 = str(row.get("sha256", "")).strip().lower()
    validation_status = str(row.get("validation_status", "")).strip()
    manifest_type = str(row.get("manifest_type", "")).strip()

    target_abs = _resolve_abs(root, target_output_path) if target_output_path else Path()
    source_abs = _resolve_abs(root, source_file) if source_file else Path()
    manifest_abs = _resolve_abs(root, source_manifest_path) if source_manifest_path else Path()

    return {
        "source_system": str(row.get("source_system", "")).strip(),
        "source_file": source_file,
        "source_file_abs": str(source_abs) if source_file else "",
        "target_output_path": target_output_path,
        "target_output_abs": str(target_abs) if target_output_path else "",
        "manifest_path": source_manifest_path,
        "manifest_abs": str(manifest_abs) if source_manifest_path else "",
        "row_count": row_count,
        "sha256": sha256,
        "producer_script": str(row.get("producer_script", "")).strip(),
        "validation_status": validation_status,
        "manifest_type": manifest_type,
        "is_manifest_valid": bool(
            target_output_path
            and source_file
            and source_manifest_path
            and row_count > 0
            and sha256
            and _status_is_validated(validation_status)
            and _manifest_type_valid(manifest_type)
        ),
        "is_forbidden": bool(
            _contains_forbidden_token(target_output_path)
            or _contains_forbidden_token(source_file)
            or _contains_forbidden_token(source_manifest_path)
        ),
    }


def run_source_materialization(root: Path) -> dict[str, Any]:
    root = Path(root)
    exports_dir = root / "data" / "exports"
    review_dir = root / "data" / "review_queue"

    manifest_rows = read_csv(exports_dir / "validated_source_manifest_inventory_r4_8i.csv")

    results_rows: list[dict[str, Any]] = []
    blocker_rows: list[dict[str, Any]] = []

    files_materialized = 0
    files_hash_validated = 0
    forbidden_artifact_usage = False
    roots = _candidate_roots(root)

    for idx, raw_row in enumerate(manifest_rows, start=1):
        record = _record_from_manifest(root, raw_row)
        source_system = str(record.get("source_system", ""))
        target_output_path = str(record.get("target_output_path", ""))
        target_abs = Path(str(record.get("target_output_abs", "")))
        expected_rows = int(record.get("row_count", 0))
        expected_sha = str(record.get("sha256", "")).strip().lower()

        status = "blocked"
        blocker_reason = ""
        candidate_used = ""
        candidate_source_path = ""
        target_exists = False
        target_rows = 0
        target_sha = ""
        copy_performed = False

        if record["is_forbidden"]:
            forbidden_artifact_usage = True
            blocker_reason = "forbidden_artifact_path_detected"
        elif not record["is_manifest_valid"]:
            blocker_reason = "invalid_manifest_record"
        else:
            candidates = _candidate_paths(
                root=root,
                target_output_path=target_output_path,
                source_file=str(record.get("source_file", "")),
                source_manifest_path=str(record.get("manifest_path", "")),
            )

            candidate_failures: list[str] = []
            for candidate in candidates:
                if not candidate.exists() or not candidate.is_file():
                    continue

                if not _is_approved_stage_path(candidate, roots):
                    candidate_failures.append(f"{candidate}:not_approved_stage_path")
                    continue

                if _contains_forbidden_token(str(candidate)):
                    candidate_failures.append(f"{candidate}:forbidden_artifact_candidate")
                    continue

                candidate_sha = _sha256(candidate).lower()
                candidate_rows = _row_count(candidate)
                if candidate_rows <= 0:
                    candidate_failures.append(f"{candidate}:zero_rows")
                    continue
                if candidate_sha != expected_sha:
                    candidate_failures.append(f"{candidate}:hash_mismatch")
                    continue

                target_abs.parent.mkdir(parents=True, exist_ok=True)
                if candidate.resolve() != target_abs.resolve():
                    shutil.copy2(candidate, target_abs)
                    copy_performed = True

                target_exists = target_abs.exists() and target_abs.is_file()
                target_rows = _row_count(target_abs)
                target_sha = _sha256(target_abs).lower()

                if not target_exists:
                    candidate_failures.append(f"{candidate}:copy_failed_target_missing")
                    continue
                if target_rows <= 0:
                    candidate_failures.append(f"{candidate}:target_zero_rows")
                    continue
                if target_sha != expected_sha:
                    candidate_failures.append(f"{candidate}:target_hash_mismatch")
                    continue

                candidate_source_path = str(candidate)
                candidate_used = _relative_posix(root, candidate) or str(candidate)
                status = "materialized_validated"
                blocker_reason = ""
                break

            if status != "materialized_validated":
                if candidate_failures:
                    blocker_reason = ";".join(candidate_failures[:3])
                else:
                    blocker_reason = "no_hash_compatible_candidate_found"

        if status == "materialized_validated":
            files_materialized += 1
            files_hash_validated += 1
        else:
            blocker_rows.append(
                {
                    "manifest_index": idx,
                    "source_system": source_system,
                    "target_output_path": target_output_path,
                    "source_file": str(record.get("source_file", "")),
                    "manifest_path": str(record.get("manifest_path", "")),
                    "blocker_reason": blocker_reason or "unknown_blocker",
                    "next_action": "external_acquisition_or_manual_file",
                }
            )

        results_rows.append(
            {
                "manifest_index": idx,
                "source_system": source_system,
                "target_output_path": target_output_path,
                "target_output_abs": str(target_abs),
                "source_file": str(record.get("source_file", "")),
                "manifest_path": str(record.get("manifest_path", "")),
                "expected_row_count": expected_rows,
                "expected_sha256": expected_sha,
                "validation_status": str(record.get("validation_status", "")),
                "manifest_type": str(record.get("manifest_type", "")),
                "manifest_record_valid": bool(record.get("is_manifest_valid", False)),
                "materialization_status": status,
                "copy_performed": copy_performed,
                "candidate_used": candidate_used,
                "candidate_source_path": candidate_source_path,
                "target_exists": target_exists
                if status == "materialized_validated"
                else target_abs.exists(),
                "target_row_count": target_rows,
                "target_sha256": target_sha,
                "hash_validated": status == "materialized_validated",
                "row_validated_nonzero": target_rows > 0
                if status == "materialized_validated"
                else False,
                "blocker_reason": blocker_reason,
            }
        )

    status_payload = {
        "generated_at": utc_now(),
        "r4_9b_manifest_records_checked": len(manifest_rows),
        "r4_9b_files_materialized": files_materialized,
        "r4_9b_files_hash_validated": files_hash_validated,
        "r4_9b_materialization_blockers": len(blocker_rows),
        "r4_9b_forbidden_artifact_usage": forbidden_artifact_usage,
        "phase_7_8_blocked": True,
        "production_status": "NON_PRODUCTION_DIAGNOSTIC",
    }

    write_csv(
        exports_dir / "source_materialization_results_r4_9b.csv",
        results_rows,
        [
            "manifest_index",
            "source_system",
            "target_output_path",
            "target_output_abs",
            "source_file",
            "manifest_path",
            "expected_row_count",
            "expected_sha256",
            "validation_status",
            "manifest_type",
            "manifest_record_valid",
            "materialization_status",
            "copy_performed",
            "candidate_used",
            "candidate_source_path",
            "target_exists",
            "target_row_count",
            "target_sha256",
            "hash_validated",
            "row_validated_nonzero",
            "blocker_reason",
        ],
    )
    write_csv(
        review_dir / "source_materialization_blockers_r4_9b.csv",
        blocker_rows,
        [
            "manifest_index",
            "source_system",
            "target_output_path",
            "source_file",
            "manifest_path",
            "blocker_reason",
            "next_action",
        ],
    )
    write_json(exports_dir / "source_materialization_status_r4_9b.json", status_payload)

    return status_payload
