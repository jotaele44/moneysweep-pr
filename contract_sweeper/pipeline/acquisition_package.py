"""Manual acquisition package builders for R4.8G."""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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
    return [piece.strip() for piece in str(raw or "").split("|") if piece.strip()]


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


def write_markdown(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def build_manual_export_steps(
    *,
    source_url_or_portal: str,
    target_dropzone_path: str,
    target_output_path: str,
    accepted_filename_patterns: str,
    required_columns: str,
    validation_command: str,
) -> str:
    portal_line = (
        f"1) Access source portal: {source_url_or_portal}"
        if source_url_or_portal
        else "1) Access the source portal for this dataset."
    )
    return (
        f"{portal_line}\n"
        "2) Export Puerto Rico-scoped records without dropping source fields.\n"
        f"3) Save file in dropzone path: {target_dropzone_path}\n"
        f"4) Ensure filename matches one of: {accepted_filename_patterns}\n"
        f"5) Ensure required columns are present: {required_columns}\n"
        f"6) Validate staged output target: {target_output_path}\n"
        f"7) Run validation command: {validation_command}"
    )


def build_manual_acquisition_rows(
    manual_rows: list[dict[str, str]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], bool]:
    matrix_rows: list[dict[str, Any]] = []
    request_rows: list[dict[str, Any]] = []
    forbidden_artifact_usage = False

    for row in sorted(manual_rows, key=lambda item: safe_int(item.get("priority"))):
        priority = safe_int(row.get("priority"))
        source_family = str(row.get("source_family", "")).strip()
        expected_input = str(row.get("expected_input", "")).strip()
        source_url_or_portal = str(row.get("source_url_or_portal", "")).strip()
        target_dropzone_path = str(row.get("target_dropzone_path", "")).strip()
        target_output_path = str(row.get("target_output_path", "")).strip()
        accepted_filename_patterns = str(row.get("accepted_filename_patterns", "")).strip()
        required_columns = str(row.get("required_columns", "")).strip()
        validation_command = str(row.get("validation_command", "")).strip()
        failure_reason = str(row.get("failure_reason", "")).strip()

        if any(
            contains_forbidden_token(path)
            for path in (expected_input, target_dropzone_path, target_output_path)
        ):
            forbidden_artifact_usage = True

        manual_export_steps = build_manual_export_steps(
            source_url_or_portal=source_url_or_portal,
            target_dropzone_path=target_dropzone_path,
            target_output_path=target_output_path,
            accepted_filename_patterns=accepted_filename_patterns,
            required_columns=required_columns,
            validation_command=validation_command,
        )

        matrix_row = {
            "priority": priority,
            "source_family": source_family,
            "expected_input": expected_input,
            "source_url_or_portal": source_url_or_portal,
            "exact_manual_export_steps": manual_export_steps,
            "required_file_type": str(row.get("required_file_type", "")).strip() or "csv",
            "accepted_filename_patterns": accepted_filename_patterns,
            "required_columns": required_columns,
            "target_dropzone_path": target_dropzone_path,
            "target_output_path": target_output_path,
            "validation_command": validation_command,
            "reason_needed": failure_reason or "manual_source_missing",
        }
        matrix_rows.append(matrix_row)

        request_row = dict(matrix_row)
        request_row["request_status"] = "pending_manual_delivery"
        request_rows.append(request_row)

    return matrix_rows, request_rows, forbidden_artifact_usage


def build_backfill_retry_order_r48g(
    *,
    retry_order_r48f: list[dict[str, str]],
    manual_rows: list[dict[str, Any]],
    endpoint_rows: list[dict[str, Any]],
    producer_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    retry_rank_hint = {
        str(row.get("expected_input", "")).strip(): safe_int(row.get("retry_rank"))
        for row in retry_order_r48f
        if str(row.get("expected_input", "")).strip()
    }

    union: dict[str, dict[str, Any]] = {}
    for row in manual_rows:
        expected_input = str(row.get("expected_input", "")).strip()
        if not expected_input:
            continue
        union[expected_input] = {
            "priority": safe_int(row.get("priority")),
            "expected_input": expected_input,
            "source_family": str(row.get("source_family", "")),
            "next_action": "require_manual_file",
            "reason": str(row.get("reason_needed", "")),
        }

    for row in endpoint_rows:
        expected_input = str(row.get("expected_input", "")).strip()
        if not expected_input:
            continue
        union.setdefault(
            expected_input,
            {
                "priority": safe_int(row.get("priority")),
                "expected_input": expected_input,
                "source_family": str(row.get("source_family", "")),
                "next_action": str(row.get("recommended_endpoint_action", "endpoint_resolution_required")),
                "reason": str(row.get("reason_blocked", "")),
            },
        )

    for row in producer_rows:
        expected_input = str(row.get("expected_input", "")).strip()
        if not expected_input:
            continue
        union.setdefault(
            expected_input,
            {
                "priority": safe_int(row.get("priority")),
                "expected_input": expected_input,
                "source_family": str(row.get("source_family", "")),
                "next_action": (
                    "require_manual_file"
                    if str(row.get("manual_source_required", "")).lower() == "true"
                    else "apply_patch_and_retry"
                ),
                "reason": str(row.get("failure_reason", "")),
            },
        )

    out_rows: list[dict[str, Any]] = []
    for expected_input, row in sorted(
        union.items(),
        key=lambda item: (
            safe_int(item[1].get("priority")),
            retry_rank_hint.get(item[0], 0),
            item[0],
        ),
    ):
        out_rows.append(
            {
                "retry_rank": len(out_rows) + 1,
                "priority": safe_int(row.get("priority")),
                "expected_input": expected_input,
                "source_family": str(row.get("source_family", "")),
                "next_action": str(row.get("next_action", "")),
                "reason": str(row.get("reason", "")),
            }
        )
    return out_rows


def build_acquisition_markdown(
    *,
    generated_at: str,
    manual_count: int,
    endpoint_count: int,
    producer_count: int,
    credential_count: int,
) -> str:
    return (
        "# R4.8G Acquisition Package\n\n"
        f"- Generated at: `{generated_at}`\n"
        f"- Manual file requests: `{manual_count}`\n"
        f"- Credential requests: `{credential_count}`\n"
        f"- Endpoint resolution requests: `{endpoint_count}`\n"
        f"- Producer patch requests: `{producer_count}`\n\n"
        "This package is non-executing and planning-only. "
        "No downloads, ingest, or staging operations were performed.\n"
    )
