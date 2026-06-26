"""Manual fallback package generation for R4.8E."""

from __future__ import annotations

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


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def split_pipe(raw: Any) -> list[str]:
    return [part.strip() for part in str(raw or "").split("|") if part.strip()]


def contains_forbidden_token(text: str) -> bool:
    lowered = str(text or "").lower()
    return any(token in lowered for token in FORBIDDEN_ARTIFACT_TOKENS)


def default_required_file_type(path: str) -> str:
    suffix = Path(path).suffix.lower().lstrip(".")
    if suffix:
        return suffix
    return "csv"


def default_filename_patterns(path: str) -> str:
    name = Path(path).name
    stem = Path(path).stem
    suffix = Path(path).suffix.lower()
    if suffix == ".csv":
        return f"{name}|{stem}*.csv|*.csv"
    if suffix == ".parquet":
        return f"{name}|{stem}*.parquet|*.parquet"
    if suffix in {".xlsx", ".xls"}:
        return f"{name}|{stem}*.xlsx|{stem}*.xls|*.xlsx|*.xls"
    return f"{name}|{stem}*|*.csv|*.parquet|*.xlsx|*.xls"


def default_dropzone(source_family: str, expected_input: str) -> str:
    source_slug = "".join(ch if ch.isalnum() else "_" for ch in source_family.lower()).strip("_")
    if not source_slug:
        source_slug = "source"
    filename = Path(expected_input).name or "manual_input.csv"
    return f"data/manual_import_dropzone/r4_8e/{source_slug}/{filename}"


def safe_int(raw: Any) -> int:
    try:
        return int(float(str(raw or "0").strip()))
    except (TypeError, ValueError):
        return 0


def build_manual_export_steps(
    *,
    source_family: str,
    source_url_or_portal: str,
    required_env_vars: str,
    producer_script: str,
    target_dropzone_path: str,
    validation_command: str,
) -> str:
    portal_line = (
        f"1) Open source portal: {source_url_or_portal}"
        if source_url_or_portal
        else "1) Identify the authoritative portal for this source family."
    )
    env_line = (
        f"2) Ensure required environment variables are configured: {required_env_vars}"
        if required_env_vars
        else "2) Confirm no secrets are embedded in exported files."
    )
    return (
        f"{portal_line}\n"
        f"{env_line}\n"
        "3) Export the source dataset for Puerto Rico scope and preserve raw columns.\n"
        f"4) Save exported file to dropzone path: {target_dropzone_path}\n"
        f"5) Validate staged file with: {validation_command}\n"
        f"6) If validation fails, queue remediation with source family '{source_family}' and producer '{producer_script}'."
    )


def build_manual_fallback_package(
    *,
    manual_rows: list[dict[str, str]],
    runner_manifest_by_input: dict[str, dict[str, str]],
    retry_results_by_input: dict[str, dict[str, str]],
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], bool]:
    """Build R4.8E manual fallback package rows and payload."""

    inventory_rows: list[dict[str, Any]] = []
    manual_required_rows: list[dict[str, Any]] = []
    forbidden_artifact_usage = False

    for row in sorted(
        manual_rows, key=lambda item: int(float(str(item.get("priority", "0") or "0")))
    ):
        expected_input = str(row.get("expected_input", "")).strip()
        runner_row = runner_manifest_by_input.get(expected_input, {})
        retry_row = retry_results_by_input.get(expected_input, {})

        source_family = str(
            row.get("source_family")
            or runner_row.get("source_family")
            or retry_row.get("source_family")
            or "unknown_source"
        ).strip()
        target_output_path = str(
            row.get("target_output_path") or runner_row.get("target_output_path") or expected_input
        ).strip()
        required_columns = str(runner_row.get("expected_schema", "")).strip()
        validation_command = str(runner_row.get("validation_command", "")).strip()
        if not validation_command:
            validation_command = (
                "python -c \"from pathlib import Path; p=Path('"
                + target_output_path
                + "'); assert p.exists(), 'missing output'; print('ok')\""
            )

        source_url_or_portal = str(runner_row.get("source_url_or_portal", "")).strip()
        required_env_vars = str(runner_row.get("required_env_vars", "")).strip()
        producer_script = str(
            runner_row.get("likely_producer_script") or retry_row.get("producer_script") or ""
        ).strip()

        required_file_type = default_required_file_type(target_output_path)
        accepted_filename_patterns = default_filename_patterns(target_output_path)
        target_dropzone_path = default_dropzone(source_family, expected_input)

        manual_steps = build_manual_export_steps(
            source_family=source_family,
            source_url_or_portal=source_url_or_portal,
            required_env_vars=required_env_vars,
            producer_script=producer_script,
            target_dropzone_path=target_dropzone_path,
            validation_command=validation_command,
        )

        if any(
            contains_forbidden_token(value)
            for value in (
                expected_input,
                target_output_path,
                target_dropzone_path,
            )
        ):
            forbidden_artifact_usage = True

        inventory_row = {
            "priority": row.get("priority", ""),
            "source_family": source_family,
            "expected_input": expected_input,
            "required_file_type": required_file_type,
            "accepted_filename_patterns": accepted_filename_patterns,
            "required_columns": required_columns,
            "target_dropzone_path": target_dropzone_path,
            "target_output_path": target_output_path,
            "validation_command": validation_command,
            "source_url_or_portal": source_url_or_portal,
            "manual_export_steps": manual_steps,
            "producer_script": producer_script,
            "required_env_vars": required_env_vars,
            "retry_status": row.get("retry_status", ""),
            "failure_reason": row.get("failure_reason", ""),
            "next_action": "require_manual_file",
            "forbidden_artifact_usage": "False",
        }
        inventory_rows.append(inventory_row)

        required_row = dict(inventory_row)
        required_row["manual_file_received"] = "False"
        required_row["review_status"] = "pending_manual_file"
        manual_required_rows.append(required_row)

    payload = {
        "generated_at": _utc_now(),
        "phase_type": "R4.8E_MANUAL_FALLBACK_PACKAGE",
        "manual_fallback_source_count": len(inventory_rows),
        "forbidden_artifact_usage": forbidden_artifact_usage,
        "sources": inventory_rows,
    }
    return payload, inventory_rows, manual_required_rows, forbidden_artifact_usage
