"""Endpoint follow-up patch retry support for R4.8F."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from contract_sweeper.pipeline.manual_import_dropzone import (
    build_manifest,
    contains_forbidden_token,
    record_count,
    safe_int,
    sha256_file,
    split_pipe,
)

DETERMINISTIC_ENDPOINT_COMMANDS = {
    "scripts/download_grants.py": "python scripts/download_grants.py --force",
    "scripts/download_fema.py": "python scripts/download_fema.py --force",
    "scripts/download_research.py": "python scripts/download_research.py --force",
    "scripts/download_cdbg_dr.py": "python scripts/download_cdbg_dr.py --force",
    "scripts/auto_download.py": "python scripts/auto_download.py --only usaspending --force",
}


def _stderr_excerpt_safe(text: str, max_len: int = 320) -> str:
    cleaned = str(text or "").replace("\n", " ").replace("\r", " ").strip()
    return " ".join(cleaned.split())[:max_len]


def _run_command(root: Path, command: str, timeout_s: int) -> tuple[bool, int, str]:
    if not command.strip():
        return False, 1, "missing command"
    try:
        completed = subprocess.run(
            command,
            shell=True,
            cwd=str(root),
            text=True,
            capture_output=True,
            timeout=max(1, int(timeout_s)),
            check=False,
        )
    except subprocess.TimeoutExpired:
        return False, 124, f"command timed out after {timeout_s}s"

    merged = (completed.stdout or "")
    if completed.stderr:
        merged = merged + ("\n" if merged else "") + completed.stderr
    excerpt = _stderr_excerpt_safe(merged)
    if completed.returncode == 0:
        return True, 0, excerpt
    return False, int(completed.returncode), excerpt or f"command failed ({completed.returncode})"


def _required_row_by_input(
    manual_rows: list[dict[str, str]],
) -> dict[str, dict[str, str]]:
    return {
        str(row.get("expected_input", "")).strip(): row
        for row in manual_rows
        if str(row.get("expected_input", "")).strip()
    }


def _validate_staged_output(
    root: Path,
    *,
    target_output_path: str,
    required_columns_raw: str,
) -> tuple[bool, int, str, str]:
    target_abs = root / target_output_path
    rows = record_count(target_abs)
    digest = sha256_file(target_abs)
    if rows <= 0:
        return False, rows, digest, "target output has zero rows"
    if not digest:
        return False, rows, digest, "target output missing sha256"

    required_columns = split_pipe(required_columns_raw)
    if required_columns:
        try:
            import pandas as pd

            if target_abs.suffix.lower() == ".csv":
                frame = pd.read_csv(target_abs, dtype=str, low_memory=False)
            elif target_abs.suffix.lower() == ".parquet":
                frame = pd.read_parquet(target_abs)
            else:
                frame = pd.read_csv(target_abs, dtype=str, low_memory=False)
            missing = [column for column in required_columns if column not in frame.columns]
        except Exception as exc:
            return False, rows, digest, f"unable to validate required columns: {exc}"
        if missing:
            return False, rows, digest, "missing required columns: " + "|".join(missing)
    return True, rows, digest, ""


def run_endpoint_patch_retries(
    root: Path,
    *,
    endpoint_rows: list[dict[str, str]],
    manual_rows: list[dict[str, str]],
    command_timeout_s: int = 30,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, int], bool]:
    root = Path(root)
    required_by_input = _required_row_by_input(manual_rows)

    report_rows: list[dict[str, Any]] = []
    remaining_rows: list[dict[str, Any]] = []
    new_manifests: list[dict[str, Any]] = []
    forbidden_artifact_usage = False

    endpoint_patches_applied = 0
    endpoint_retries_attempted = 0
    endpoint_retries_successful = 0

    for row in sorted(endpoint_rows, key=lambda item: safe_int(item.get("priority"))):
        priority = safe_int(row.get("priority"))
        expected_input = str(row.get("expected_input", "")).strip()
        source_family = str(row.get("source_family", "")).strip()
        producer_script = str(row.get("producer_script", "")).strip()
        endpoint_classification = str(row.get("endpoint_classification", "")).strip()
        next_action = str(row.get("next_action", "")).strip()
        source_url_or_portal = str(row.get("source_url_or_portal", "")).strip()

        manual_row = required_by_input.get(expected_input, {})
        target_output_path = str(
            manual_row.get("target_output_path")
            or expected_input
        ).strip()
        required_columns = str(manual_row.get("required_columns", "")).strip()

        report = {
            "priority": priority,
            "expected_input": expected_input,
            "source_family": source_family,
            "producer_script": producer_script,
            "endpoint_classification": endpoint_classification,
            "next_action": next_action,
            "source_url_or_portal": source_url_or_portal,
            "target_output_path": target_output_path,
            "deterministic_patch_applied": False,
            "retry_attempted": False,
            "retry_status": "pending",
            "retry_command": "",
            "command_exit_code": "",
            "command_excerpt_safe": "",
            "row_count": 0,
            "sha256": "",
            "manifest_written": False,
            "failure_reason": "",
        }

        if any(
            contains_forbidden_token(path)
            for path in (expected_input, target_output_path)
        ):
            forbidden_artifact_usage = True
            report["retry_status"] = "blocked_forbidden_artifact"
            report["failure_reason"] = "forbidden artifact token detected"
            report_rows.append(report)
            remaining_rows.append({**report, "review_status": "pending"})
            continue

        command = DETERMINISTIC_ENDPOINT_COMMANDS.get(producer_script, "")
        if command:
            report["deterministic_patch_applied"] = True
            endpoint_patches_applied += 1
            report["retry_command"] = command
        else:
            report["retry_status"] = "no_deterministic_patch_available"
            report["failure_reason"] = "no safe deterministic endpoint patch command"
            report_rows.append(report)
            remaining_rows.append({**report, "review_status": "pending"})
            continue

        report["retry_attempted"] = True
        endpoint_retries_attempted += 1

        ok, exit_code, excerpt = _run_command(root, command, timeout_s=command_timeout_s)
        report["command_exit_code"] = str(exit_code)
        report["command_excerpt_safe"] = excerpt
        if not ok:
            report["retry_status"] = "failed_command"
            report["failure_reason"] = excerpt or f"command failed ({exit_code})"
            report_rows.append(report)
            remaining_rows.append({**report, "review_status": "pending"})
            continue

        valid, rows, digest, reason = _validate_staged_output(
            root,
            target_output_path=target_output_path,
            required_columns_raw=required_columns,
        )
        report["row_count"] = rows
        report["sha256"] = digest
        if not valid:
            report["retry_status"] = "failed_validation"
            report["failure_reason"] = reason
            report_rows.append(report)
            remaining_rows.append({**report, "review_status": "pending"})
            continue

        manifest_row = build_manifest(
            root,
            priority=priority,
            source_system=source_family or "endpoint_retry_source",
            source_file=target_output_path,
            target_output_path=target_output_path,
            row_count=rows,
            producer_script=producer_script,
            known_gaps="r4_8f_endpoint_retry",
        )
        new_manifests.append(manifest_row)

        report["manifest_written"] = True
        report["retry_status"] = "success"
        endpoint_retries_successful += 1
        report_rows.append(report)

    metrics = {
        "endpoint_followups_reviewed": len(endpoint_rows),
        "endpoint_patches_applied": endpoint_patches_applied,
        "endpoint_retries_attempted": endpoint_retries_attempted,
        "endpoint_retries_successful": endpoint_retries_successful,
    }
    return report_rows, remaining_rows, new_manifests, metrics, forbidden_artifact_usage
