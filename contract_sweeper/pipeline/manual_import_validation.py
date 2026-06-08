"""Manual import slot generation and validation for controlled backfill."""

from __future__ import annotations

import csv
import fnmatch
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


def _split_pipe(raw: str) -> list[str]:
    return [part.strip() for part in str(raw or "").split("|") if part.strip()]


def _contains_forbidden_token(text: str) -> bool:
    lowered = str(text).lower()
    return any(token in lowered for token in FORBIDDEN_ARTIFACT_TOKENS)


def _slug(source_family: str) -> str:
    value = "".join(ch if ch.isalnum() else "_" for ch in source_family.lower())
    while "__" in value:
        value = value.replace("__", "_")
    return value.strip("_") or "source"


def _default_dropzone(source_family: str, expected_input: str) -> str:
    filename = Path(expected_input).name
    return f"data/manual_import_dropzone/{_slug(source_family)}/{filename}"


def _default_patterns(target_output_path: str) -> str:
    suffix = Path(target_output_path).suffix.lower()
    if suffix == ".parquet":
        return "*.parquet"
    if suffix == ".csv":
        return "*.csv"
    return "*.csv|*.xlsx|*.xls|*.parquet"


def build_manual_import_slots(
    manifest_rows: list[dict[str, Any]],
    existing_slots: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    slots: dict[str, dict[str, Any]] = {}

    for row in existing_slots:
        expected_input = str(row.get("expected_input", "")).strip()
        if not expected_input:
            continue
        slots[expected_input] = {
            "slot_id": str(row.get("slot_id", "")) or f"slot_{Path(expected_input).stem}",
            "source_family": str(row.get("source_family", "unknown")),
            "expected_input": expected_input,
            "dropzone_path": str(row.get("dropzone_path", ""))
            or _default_dropzone(str(row.get("source_family", "unknown")), expected_input),
            "accepted_file_patterns": str(row.get("accepted_file_patterns", ""))
            or _default_patterns(str(row.get("target_output_path") or expected_input)),
            "required_columns": str(row.get("required_columns", "")),
            "target_output_path": str(row.get("target_output_path") or expected_input),
            "manifest_output_path": str(
                row.get("manifest_output_path")
                or f"{str(row.get('target_output_path') or expected_input)}.manifest.json"
            ),
            "source_classification": str(
                row.get("source_classification", "manual_import_required")
            ),
        }

    for row in manifest_rows:
        expected_input = str(row.get("expected_input", "")).strip()
        classification = str(row.get("classification", "")).strip()
        if not expected_input:
            continue
        if classification not in {"manual_import_required", "missing_credentials"}:
            continue

        if expected_input in slots:
            continue

        source_family = str(row.get("source_family", "unknown"))
        target_output = str(row.get("target_output_path") or expected_input)
        required_columns = str(row.get("expected_schema", ""))

        slots[expected_input] = {
            "slot_id": f"slot_{int(float(str(row.get('priority', 0) or 0))):02d}_{Path(expected_input).stem}",
            "source_family": source_family,
            "expected_input": expected_input,
            "dropzone_path": _default_dropzone(source_family, expected_input),
            "accepted_file_patterns": _default_patterns(target_output),
            "required_columns": required_columns,
            "target_output_path": target_output,
            "manifest_output_path": f"{target_output}.manifest.json",
            "source_classification": classification,
        }

    return sorted(slots.values(), key=lambda r: str(r.get("slot_id", "")))


def _read_tabular(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(path, dtype=str, low_memory=False)
    if suffix == ".parquet":
        return pd.read_parquet(path)
    raise ValueError(f"unsupported manual import format: {path}")


def validate_manual_import_slots(
    root: Path, slots: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    root = Path(root)

    validation_rows: list[dict[str, Any]] = []
    error_rows: list[dict[str, Any]] = []

    for slot in slots:
        slot_id = str(slot.get("slot_id", ""))
        source_family = str(slot.get("source_family", ""))
        expected_input = str(slot.get("expected_input", ""))
        dropzone_rel = str(slot.get("dropzone_path", ""))
        target_output = str(slot.get("target_output_path", expected_input))
        required_columns = _split_pipe(slot.get("required_columns", ""))
        patterns = _split_pipe(slot.get("accepted_file_patterns", ""))

        row = {
            "slot_id": slot_id,
            "source_family": source_family,
            "expected_input": expected_input,
            "dropzone_path": dropzone_rel,
            "accepted_file_patterns": str(slot.get("accepted_file_patterns", "")),
            "required_columns": str(slot.get("required_columns", "")),
            "target_output_path": target_output,
            "manifest_output_path": str(slot.get("manifest_output_path", "")),
            "source_classification": str(
                slot.get("source_classification", "manual_import_required")
            ),
            "slot_status": "pending_manual_file",
            "validation_passed": False,
            "error_reason": "",
        }

        if (
            _contains_forbidden_token(expected_input)
            or _contains_forbidden_token(dropzone_rel)
            or _contains_forbidden_token(target_output)
        ):
            row["slot_status"] = "rejected_forbidden_artifact"
            row["error_reason"] = "forbidden artifact token detected"
            validation_rows.append(row)
            error_rows.append(row.copy())
            continue

        if not dropzone_rel:
            row["slot_status"] = "invalid_slot"
            row["error_reason"] = "missing dropzone_path"
            validation_rows.append(row)
            error_rows.append(row.copy())
            continue

        dropzone_abs = root / dropzone_rel
        if not dropzone_abs.exists() or not dropzone_abs.is_file():
            row["slot_status"] = "pending_manual_file"
            row["error_reason"] = "manual file not present in dropzone"
            validation_rows.append(row)
            error_rows.append(row.copy())
            continue

        if patterns and not any(
            fnmatch.fnmatch(dropzone_abs.name, pattern) for pattern in patterns
        ):
            row["slot_status"] = "invalid_filename"
            row["error_reason"] = "dropzone file does not match accepted_file_patterns"
            validation_rows.append(row)
            error_rows.append(row.copy())
            continue

        try:
            frame = _read_tabular(dropzone_abs)
        except Exception as exc:  # pragma: no cover - defensive branch
            row["slot_status"] = "read_error"
            row["error_reason"] = f"unable to read dropzone file: {exc}"
            validation_rows.append(row)
            error_rows.append(row.copy())
            continue

        missing_cols = [col for col in required_columns if col and col not in frame.columns]
        if missing_cols:
            row["slot_status"] = "missing_required_columns"
            row["error_reason"] = "missing required columns: " + "|".join(missing_cols)
            validation_rows.append(row)
            error_rows.append(row.copy())
            continue

        row["slot_status"] = "validated_ready"
        row["validation_passed"] = True
        row["error_reason"] = ""
        validation_rows.append(row)

    return validation_rows, error_rows


def write_manual_import_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "slot_id",
        "source_family",
        "expected_input",
        "dropzone_path",
        "accepted_file_patterns",
        "required_columns",
        "target_output_path",
        "manifest_output_path",
        "source_classification",
        "slot_status",
        "validation_passed",
        "error_reason",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
