"""Deterministic schema alignment utilities for R4.8D targeted retries."""

from __future__ import annotations

import json
import re
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


def split_pipe(raw: Any) -> list[str]:
    return [part.strip() for part in str(raw or "").split("|") if part.strip()]


def _contains_forbidden_token(text: str) -> bool:
    lowered = str(text).lower()
    return any(token in lowered for token in FORBIDDEN_ARTIFACT_TOKENS)


def _normalize_name(value: Any) -> str:
    text = str(value or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text.upper()


def _read_table(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(path, dtype=str, low_memory=False)
    if suffix == ".parquet":
        return pd.read_parquet(path)
    raise ValueError(f"unsupported tabular format: {path}")


def _write_table(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    suffix = path.suffix.lower()
    if suffix == ".csv":
        frame.to_csv(path, index=False, encoding="utf-8")
        return
    if suffix == ".parquet":
        frame.to_parquet(path, index=False)
        return
    raise ValueError(f"unsupported tabular format: {path}")


def _load_mapping(raw: str) -> dict[str, str]:
    text = str(raw or "").strip()
    if not text:
        return {}
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return {}
    if not isinstance(payload, dict):
        return {}
    return {str(k): str(v) for k, v in payload.items() if str(k).strip() and str(v).strip()}


def align_source_schema(
    root: Path,
    *,
    expected_input: str,
    target_output_path: str,
    source_family: str,
    required_columns_raw: str,
    recommended_mapping_raw: str,
) -> dict[str, Any]:
    """Apply deterministic schema alignment to a staged source file.

    Returns a report row with before/after schema state.
    """

    root = Path(root)
    target_rel = str(target_output_path or expected_input).strip()
    target_abs = root / target_rel

    report = {
        "expected_input": expected_input,
        "target_output_path": target_rel,
        "source_family": source_family,
        "alignment_attempted": False,
        "alignment_applied": False,
        "deterministic_mapping": True,
        "forbidden_artifact_usage": False,
        "row_count": 0,
        "observed_columns_before": "",
        "observed_columns_after": "",
        "required_columns": required_columns_raw,
        "missing_columns_before": "",
        "missing_columns_after": "",
        "applied_mapping": "{}",
        "alignment_added_count": 0,
        "alignment_status": "not_attempted",
        "failure_reason": "",
    }

    if _contains_forbidden_token(expected_input) or _contains_forbidden_token(target_rel):
        report["forbidden_artifact_usage"] = True
        report["deterministic_mapping"] = False
        report["alignment_status"] = "forbidden_artifact_rejected"
        report["failure_reason"] = "forbidden artifact token detected"
        return report

    required_columns = split_pipe(required_columns_raw)
    mapping = _load_mapping(recommended_mapping_raw)

    if not target_abs.exists() or not target_abs.is_file():
        report["alignment_status"] = "missing_target_file"
        report["failure_reason"] = "target output file not found"
        return report

    try:
        frame = _read_table(target_abs)
    except Exception as exc:
        report["alignment_status"] = "read_error"
        report["failure_reason"] = f"unable to read target output: {exc}"
        return report

    report["alignment_attempted"] = True
    report["row_count"] = int(len(frame))
    report["observed_columns_before"] = "|".join(str(col) for col in frame.columns)

    missing_before = [col for col in required_columns if col not in frame.columns]
    report["missing_columns_before"] = "|".join(missing_before)

    applied_mapping: dict[str, str] = {}

    def assign_from_column(dest: str, source: str) -> bool:
        if source in frame.columns:
            frame[dest] = frame[source].astype(str)
            applied_mapping[dest] = source
            return True
        return False

    def assign_constant(dest: str, value: str) -> None:
        frame[dest] = str(value)
        applied_mapping[dest] = f"CONST:{value}"

    for missing in missing_before:
        if missing in frame.columns:
            continue

        mapped = False
        source_col = mapping.get(missing, "")
        if source_col:
            mapped = assign_from_column(missing, source_col)

        if mapped:
            continue

        # Deterministic fallbacks for canonical lineage fields.
        if missing == "recipient_name_normalized" and "recipient_name" in frame.columns:
            frame[missing] = frame["recipient_name"].apply(_normalize_name)
            applied_mapping[missing] = "FUNC:normalize(recipient_name)"
            continue

        if missing == "source_system":
            if "source_dataset" in frame.columns:
                assign_from_column(missing, "source_dataset")
                continue
            assign_constant(missing, source_family)
            continue

        if missing == "source_record_id":
            for candidate in ("award_id", "prime_award_id", "sub_award_id"):
                if assign_from_column(missing, candidate):
                    break
            else:
                report["deterministic_mapping"] = False
            continue

        if missing == "source_lineage_path":
            if assign_from_column(missing, "source_file"):
                continue
            assign_constant(missing, expected_input)
            continue

        if missing == "source_lineage_mode":
            if "source_dataset" in frame.columns:
                assign_from_column(missing, "source_dataset")
                continue
            assign_constant(missing, "schema_alignment_retry")
            continue

        report["deterministic_mapping"] = False

    missing_after = [col for col in required_columns if col not in frame.columns]
    report["missing_columns_after"] = "|".join(missing_after)
    report["observed_columns_after"] = "|".join(str(col) for col in frame.columns)
    report["applied_mapping"] = json.dumps(applied_mapping, sort_keys=True)
    report["alignment_added_count"] = int(len(applied_mapping))

    if applied_mapping:
        try:
            _write_table(target_abs, frame)
            report["alignment_applied"] = True
        except Exception as exc:
            report["alignment_status"] = "write_error"
            report["failure_reason"] = f"unable to write aligned output: {exc}"
            return report

    if missing_after:
        report["alignment_status"] = "unresolved_missing_columns"
        report["failure_reason"] = "required columns still missing after deterministic alignment"
        return report

    report["alignment_status"] = "aligned" if report["alignment_applied"] else "already_aligned"
    return report
