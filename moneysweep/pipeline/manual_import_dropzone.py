"""Manual import dropzone execution support for R4.8F."""

from __future__ import annotations

import csv
import fnmatch
import hashlib
import json
import shutil
from datetime import datetime, timezone
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


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def safe_int(raw: Any) -> int:
    try:
        return int(float(str(raw or "0").strip()))
    except (TypeError, ValueError):
        return 0


def split_pipe(raw: Any) -> list[str]:
    return [item.strip() for item in str(raw or "").split("|") if item.strip()]


def contains_forbidden_token(text: str) -> bool:
    lowered = str(text or "").lower()
    return any(token in lowered for token in FORBIDDEN_ARTIFACT_TOKENS)


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def sha256_file(path: Path) -> str:
    if not path.exists() or not path.is_file():
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_table(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(path, dtype=str, low_memory=False).fillna("")
    if suffix == ".parquet":
        return pd.read_parquet(path).fillna("")
    if suffix in {".xlsx", ".xls"}:
        return pd.read_excel(path, dtype=str).fillna("")
    raise ValueError(f"unsupported table format: {path}")


def _write_table(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    suffix = path.suffix.lower()
    if suffix == ".csv":
        frame.to_csv(path, index=False, encoding="utf-8")
        return
    if suffix == ".parquet":
        frame.to_parquet(path, index=False)
        return
    raise ValueError(f"unsupported target format: {path}")


def record_count(path: Path) -> int:
    if not path.exists() or not path.is_file():
        return 0
    try:
        frame = _read_table(path)
    except Exception:
        return 0
    return int(len(frame))


def build_manifest(
    root: Path,
    *,
    priority: int,
    source_system: str,
    source_file: str,
    target_output_path: str,
    row_count: int,
    producer_script: str,
    known_gaps: str = "",
) -> dict[str, Any]:
    target_abs = root / target_output_path
    manifest = {
        "source_system": source_system,
        "source_file": source_file,
        "target_output_path": target_output_path,
        "row_count": int(row_count),
        "sha256": sha256_file(target_abs),
        "generated_at": utc_now(),
        "producer_script": producer_script,
        "validation_status": "validated",
        "known_gaps": known_gaps,
        "schema_version": "r4_8f_schema_v1",
        "manifest_type": "validated_source_manifest",
    }

    safe_stem = Path(target_output_path).stem or "source"
    safe_stem = "".join(ch if ch.isalnum() else "_" for ch in safe_stem).strip("_") or "source"
    manifest_relpath = f"data/manifests/r4_8f/{priority:02d}_{safe_stem}.manifest.json"
    write_json(root / manifest_relpath, manifest)

    out_row = dict(manifest)
    out_row["manifest_path"] = manifest_relpath
    return out_row


def _select_candidate(
    *,
    root: Path,
    dropzone_relpath: str,
    accepted_patterns: list[str],
) -> tuple[Path | None, str]:
    dropzone_abs = root / dropzone_relpath
    if dropzone_abs.exists() and dropzone_abs.is_file():
        candidates = [dropzone_abs]
    else:
        parent = dropzone_abs if dropzone_abs.is_dir() else dropzone_abs.parent
        if not parent.exists() or not parent.is_dir():
            return None, "dropzone_missing"
        candidates = [path for path in parent.iterdir() if path.is_file()]

    if not candidates:
        return None, "no_file_present"

    if not accepted_patterns:
        picked = sorted(candidates, key=lambda path: path.stat().st_mtime, reverse=True)[0]
        return picked, ""

    matching = []
    for candidate in candidates:
        for pattern in accepted_patterns:
            if fnmatch.fnmatch(candidate.name, pattern):
                matching.append(candidate)
                break

    if not matching:
        return None, "pattern_mismatch"

    picked = sorted(matching, key=lambda path: path.stat().st_mtime, reverse=True)[0]
    return picked, ""


def _stage_candidate_to_target(
    *,
    candidate_abs: Path,
    target_abs: Path,
) -> None:
    if candidate_abs.resolve() == target_abs.resolve():
        return

    if candidate_abs.suffix.lower() == target_abs.suffix.lower():
        target_abs.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(candidate_abs, target_abs)
        return

    frame = _read_table(candidate_abs)
    _write_table(target_abs, frame)


def process_manual_import_dropzones(
    root: Path,
    *,
    manual_rows: list[dict[str, str]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, int], bool]:
    """Validate/manual-stage files in manual import dropzones."""

    root = Path(root)

    inventory_rows: list[dict[str, Any]] = []
    still_required_rows: list[dict[str, Any]] = []
    new_manifests: list[dict[str, Any]] = []
    forbidden_artifact_usage = False

    manual_sources_checked = 0
    manual_files_found = 0
    manual_files_validated = 0

    for row in sorted(manual_rows, key=lambda item: safe_int(item.get("priority"))):
        manual_sources_checked += 1
        priority = safe_int(row.get("priority"))
        expected_input = str(row.get("expected_input", "")).strip()
        source_family = str(row.get("source_family", "")).strip()
        producer_script = str(row.get("producer_script", "")).strip()
        dropzone_relpath = str(row.get("target_dropzone_path", "")).strip()
        target_output_path = str(row.get("target_output_path", "")).strip()
        accepted_patterns = split_pipe(row.get("accepted_filename_patterns", ""))
        required_columns = split_pipe(row.get("required_columns", ""))
        validation_command = str(row.get("validation_command", "")).strip()
        source_url_or_portal = str(row.get("source_url_or_portal", "")).strip()

        paths_to_scan = [expected_input, dropzone_relpath, target_output_path]
        if any(contains_forbidden_token(path) for path in paths_to_scan):
            forbidden_artifact_usage = True

        dropzone_abs = root / dropzone_relpath if dropzone_relpath else root
        if dropzone_relpath:
            # Ensure dropzone directory path exists for manual intake.
            if dropzone_abs.suffix:
                dropzone_abs.parent.mkdir(parents=True, exist_ok=True)
            else:
                dropzone_abs.mkdir(parents=True, exist_ok=True)

        candidate_abs, selection_error = _select_candidate(
            root=root,
            dropzone_relpath=dropzone_relpath,
            accepted_patterns=accepted_patterns,
        )

        inventory = {
            "priority": priority,
            "source_family": source_family,
            "expected_input": expected_input,
            "target_dropzone_path": dropzone_relpath,
            "target_output_path": target_output_path,
            "accepted_filename_patterns": "|".join(accepted_patterns),
            "required_columns": "|".join(required_columns),
            "manual_file_found": False,
            "manual_file_validated": False,
            "selected_dropzone_file": "",
            "selected_dropzone_sha256": "",
            "selected_dropzone_rows": 0,
            "staged_output_sha256": "",
            "staged_output_rows": 0,
            "manifest_written": False,
            "review_status": "pending_manual_file",
            "failure_reason": "",
            "validation_command": validation_command,
            "source_url_or_portal": source_url_or_portal,
            "producer_script": producer_script,
            "forbidden_artifact_usage": False,
        }

        if candidate_abs is None:
            inventory["failure_reason"] = selection_error or "no_dropzone_file"
            inventory_rows.append(inventory)
            still_required_rows.append(
                {
                    "priority": priority,
                    "source_family": source_family,
                    "expected_input": expected_input,
                    "target_dropzone_path": dropzone_relpath,
                    "target_output_path": target_output_path,
                    "accepted_filename_patterns": "|".join(accepted_patterns),
                    "required_columns": "|".join(required_columns),
                    "validation_command": validation_command,
                    "source_url_or_portal": source_url_or_portal,
                    "producer_script": producer_script,
                    "manual_file_received": "False",
                    "review_status": "pending_manual_file",
                    "failure_reason": inventory["failure_reason"],
                }
            )
            continue

        manual_files_found += 1
        inventory["manual_file_found"] = True
        inventory["selected_dropzone_file"] = str(candidate_abs.relative_to(root))
        inventory["selected_dropzone_sha256"] = sha256_file(candidate_abs)

        try:
            frame = _read_table(candidate_abs)
        except Exception as exc:
            inventory["failure_reason"] = f"unable_to_read_dropzone_file: {exc}"
            inventory_rows.append(inventory)
            still_required_rows.append(
                {
                    "priority": priority,
                    "source_family": source_family,
                    "expected_input": expected_input,
                    "target_dropzone_path": dropzone_relpath,
                    "target_output_path": target_output_path,
                    "accepted_filename_patterns": "|".join(accepted_patterns),
                    "required_columns": "|".join(required_columns),
                    "validation_command": validation_command,
                    "source_url_or_portal": source_url_or_portal,
                    "producer_script": producer_script,
                    "manual_file_received": "True",
                    "review_status": "rejected_unreadable",
                    "failure_reason": inventory["failure_reason"],
                }
            )
            continue

        inventory["selected_dropzone_rows"] = int(len(frame))

        if len(frame) <= 0:
            inventory["failure_reason"] = "dropzone_file_has_zero_rows"
            inventory_rows.append(inventory)
            still_required_rows.append(
                {
                    "priority": priority,
                    "source_family": source_family,
                    "expected_input": expected_input,
                    "target_dropzone_path": dropzone_relpath,
                    "target_output_path": target_output_path,
                    "accepted_filename_patterns": "|".join(accepted_patterns),
                    "required_columns": "|".join(required_columns),
                    "validation_command": validation_command,
                    "source_url_or_portal": source_url_or_portal,
                    "producer_script": producer_script,
                    "manual_file_received": "True",
                    "review_status": "rejected_zero_rows",
                    "failure_reason": inventory["failure_reason"],
                }
            )
            continue

        missing_columns = [
            column for column in required_columns if column and column not in frame.columns
        ]
        if missing_columns:
            inventory["failure_reason"] = "missing_required_columns:" + "|".join(missing_columns)
            inventory_rows.append(inventory)
            still_required_rows.append(
                {
                    "priority": priority,
                    "source_family": source_family,
                    "expected_input": expected_input,
                    "target_dropzone_path": dropzone_relpath,
                    "target_output_path": target_output_path,
                    "accepted_filename_patterns": "|".join(accepted_patterns),
                    "required_columns": "|".join(required_columns),
                    "validation_command": validation_command,
                    "source_url_or_portal": source_url_or_portal,
                    "producer_script": producer_script,
                    "manual_file_received": "True",
                    "review_status": "rejected_missing_columns",
                    "failure_reason": inventory["failure_reason"],
                }
            )
            continue

        target_abs = root / target_output_path
        try:
            _stage_candidate_to_target(candidate_abs=candidate_abs, target_abs=target_abs)
        except Exception as exc:
            inventory["failure_reason"] = f"staging_failed: {exc}"
            inventory_rows.append(inventory)
            still_required_rows.append(
                {
                    "priority": priority,
                    "source_family": source_family,
                    "expected_input": expected_input,
                    "target_dropzone_path": dropzone_relpath,
                    "target_output_path": target_output_path,
                    "accepted_filename_patterns": "|".join(accepted_patterns),
                    "required_columns": "|".join(required_columns),
                    "validation_command": validation_command,
                    "source_url_or_portal": source_url_or_portal,
                    "producer_script": producer_script,
                    "manual_file_received": "True",
                    "review_status": "rejected_staging_failed",
                    "failure_reason": inventory["failure_reason"],
                }
            )
            continue

        staged_rows = record_count(target_abs)
        staged_sha = sha256_file(target_abs)
        if staged_rows <= 0 or not staged_sha:
            inventory["failure_reason"] = "staged_output_invalid_zero_rows_or_missing_sha256"
            inventory_rows.append(inventory)
            still_required_rows.append(
                {
                    "priority": priority,
                    "source_family": source_family,
                    "expected_input": expected_input,
                    "target_dropzone_path": dropzone_relpath,
                    "target_output_path": target_output_path,
                    "accepted_filename_patterns": "|".join(accepted_patterns),
                    "required_columns": "|".join(required_columns),
                    "validation_command": validation_command,
                    "source_url_or_portal": source_url_or_portal,
                    "producer_script": producer_script,
                    "manual_file_received": "True",
                    "review_status": "rejected_staged_invalid",
                    "failure_reason": inventory["failure_reason"],
                }
            )
            continue

        manifest_row = build_manifest(
            root,
            priority=priority,
            source_system=source_family,
            source_file=target_output_path,
            target_output_path=target_output_path,
            row_count=staged_rows,
            producer_script=producer_script or "manual_import_dropzone",
            known_gaps=f"manual_import_source={inventory['selected_dropzone_file']}",
        )
        new_manifests.append(manifest_row)

        manual_files_validated += 1
        inventory["manual_file_validated"] = True
        inventory["staged_output_rows"] = staged_rows
        inventory["staged_output_sha256"] = staged_sha
        inventory["manifest_written"] = True
        inventory["review_status"] = "validated_and_staged"
        inventory["forbidden_artifact_usage"] = False
        inventory_rows.append(inventory)

    metrics = {
        "manual_sources_checked": manual_sources_checked,
        "manual_files_found": manual_files_found,
        "manual_files_validated": manual_files_validated,
        "manual_files_still_required": len(still_required_rows),
    }
    return inventory_rows, still_required_rows, new_manifests, metrics, forbidden_artifact_usage
