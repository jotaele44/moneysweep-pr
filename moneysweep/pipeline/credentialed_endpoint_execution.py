"""Credential-aware endpoint and producer retry utilities for R4.8H."""

from __future__ import annotations

import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from moneysweep.pipeline.manual_import_dropzone import (
    contains_forbidden_token,
    record_count,
    safe_int,
    sha256_file,
    split_pipe,
)

SAFE_ENDPOINT_RETRY_COMMANDS = {
    "scripts/download_grants.py": "python scripts/download_grants.py --force",
    "scripts/download_fema.py": "python scripts/download_fema.py --force",
    "scripts/download_research.py": "python scripts/download_research.py --force",
    "scripts/download_cdbg_dr.py": "python scripts/download_cdbg_dr.py --force",
    "scripts/auto_download.py": "python scripts/auto_download.py --only usaspending --force",
}

SAFE_PRODUCER_RETRY_COMMANDS = {
    "scripts/download_subawards.py": "python scripts/download_subawards.py --force --allow-empty-success",
    "scripts/download_usace_civil.py": "python scripts/download_usace_civil.py --force --allow-empty-success",
}

_ENV_PATTERNS = (
    re.compile(r"os\.getenv\(\s*['\"]([A-Z0-9_]+)['\"]"),
    re.compile(r"os\.environ\.get\(\s*['\"]([A-Z0-9_]+)['\"]"),
    re.compile(r"os\.environ\[\s*['\"]([A-Z0-9_]+)['\"]\s*\]"),
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


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

    merged = completed.stdout or ""
    if completed.stderr:
        merged = merged + ("\n" if merged else "") + completed.stderr
    excerpt = _stderr_excerpt_safe(merged)
    if completed.returncode == 0:
        return True, 0, excerpt
    return False, int(completed.returncode), excerpt or f"command failed ({completed.returncode})"


def _read_script_required_env_vars(root: Path, producer_script: str) -> list[str]:
    if not producer_script:
        return []
    script_path = root / producer_script
    if not script_path.exists() or not script_path.is_file():
        return []

    text = script_path.read_text(encoding="utf-8", errors="ignore")
    required: list[str] = []
    for pattern in _ENV_PATTERNS:
        for match in pattern.findall(text):
            if match not in required:
                required.append(match)
    return required


def _write_manifest(
    root: Path,
    *,
    phase_tag: str,
    priority: int,
    source_system: str,
    source_file: str,
    target_output_path: str,
    row_count: int,
    producer_script: str,
    known_gaps: str,
) -> dict[str, Any]:
    target_abs = root / target_output_path

    manifest = {
        "source_system": source_system,
        "source_file": source_file,
        "target_output_path": target_output_path,
        "row_count": int(row_count),
        "sha256": sha256_file(target_abs),
        "generated_at": _utc_now(),
        "producer_script": producer_script,
        "validation_status": "validated",
        "known_gaps": known_gaps,
        "schema_version": "r4_8h_schema_v1",
        "manifest_type": "validated_source_manifest",
    }

    stem = Path(target_output_path).stem or "source"
    safe_stem = "".join(ch if ch.isalnum() else "_" for ch in stem).strip("_") or "source"
    relpath = f"data/manifests/r4_8h/{phase_tag}/{priority:02d}_{safe_stem}.manifest.json"
    manifest_path = root / relpath
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")

    out = dict(manifest)
    out["manifest_path"] = relpath
    return out


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
            missing = [
                column for column in required_columns if column and column not in frame.columns
            ]
        except Exception as exc:  # pragma: no cover - defensive
            return False, rows, digest, f"unable to validate required columns: {exc}"

        if missing:
            return False, rows, digest, "missing required columns: " + "|".join(missing)

    return True, rows, digest, ""


def evaluate_credential_requests(
    root: Path,
    *,
    credential_request_rows: list[dict[str, str]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, dict[str, Any]], int, int, bool]:
    """Evaluate credentials by env-var name only; never read/emit secret values."""

    root = Path(root)
    evaluations: list[dict[str, Any]] = []
    missing_rows: list[dict[str, Any]] = []
    by_expected_input: dict[str, dict[str, Any]] = {}
    forbidden_artifact_usage = False

    for row in sorted(credential_request_rows, key=lambda item: safe_int(item.get("priority"))):
        priority = safe_int(row.get("priority"))
        expected_input = str(row.get("expected_input", "")).strip()
        source_family = str(row.get("source_family", "")).strip()
        producer_script = str(row.get("producer_script", "")).strip()
        endpoint_classification = str(row.get("endpoint_classification", "")).strip()
        source_url_or_portal = str(row.get("source_url_or_portal", "")).strip()
        reason_blocked = str(row.get("reason_blocked", "")).strip()

        if contains_forbidden_token(expected_input):
            forbidden_artifact_usage = True

        required_env_vars = _read_script_required_env_vars(root, producer_script)
        missing_env_vars = [
            name for name in required_env_vars if not str(os.getenv(name, "")).strip()
        ]
        credentials_available = len(missing_env_vars) == 0

        eval_row: dict[str, Any] = {
            "priority": priority,
            "source_family": source_family,
            "expected_input": expected_input,
            "endpoint_classification": endpoint_classification,
            "source_url_or_portal": source_url_or_portal,
            "producer_script": producer_script,
            "required_credentials_or_auth_status": str(
                row.get("required_credentials_or_auth_status", "")
            ).strip(),
            "required_env_vars": "|".join(required_env_vars),
            "missing_env_vars": "|".join(missing_env_vars),
            "credentials_available": credentials_available,
            "reason_blocked": reason_blocked,
            "credential_check_status": "available" if credentials_available else "missing",
        }
        evaluations.append(eval_row)
        by_expected_input[expected_input] = eval_row

        if not credentials_available:
            missing_rows.append(
                {
                    **eval_row,
                    "review_status": "pending_credentials",
                }
            )

    return (
        evaluations,
        missing_rows,
        by_expected_input,
        len(evaluations) - len(missing_rows),
        len(missing_rows),
        forbidden_artifact_usage,
    )


def run_credentialed_endpoint_retries(
    root: Path,
    *,
    endpoint_rows: list[dict[str, str]],
    manual_rows_by_input: dict[str, dict[str, str]],
    credential_eval_by_input: dict[str, dict[str, Any]],
    command_timeout_s: int = 20,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, int], bool]:
    """Run bounded endpoint retries only when credential checks pass."""

    root = Path(root)
    results: list[dict[str, Any]] = []
    still_blocked: list[dict[str, Any]] = []
    new_manifests: list[dict[str, Any]] = []
    forbidden_artifact_usage = False

    retries_attempted = 0
    retries_successful = 0

    for row in sorted(endpoint_rows, key=lambda item: safe_int(item.get("priority"))):
        priority = safe_int(row.get("priority"))
        expected_input = str(row.get("expected_input", "")).strip()
        source_family = str(row.get("source_family", "")).strip()
        producer_script = str(row.get("producer_script", "")).strip()
        endpoint_classification = str(row.get("endpoint_classification", "")).strip()
        recommended_action = str(row.get("recommended_endpoint_action", "")).strip()

        manual_row = manual_rows_by_input.get(expected_input, {})
        target_output_path = str(
            manual_row.get("target_output_path") or row.get("target_output_path") or expected_input
        ).strip()
        required_columns = str(manual_row.get("required_columns", "")).strip()

        cred = credential_eval_by_input.get(expected_input, {})
        required_env_vars = str(cred.get("required_env_vars", "")).strip()
        missing_env_vars = str(cred.get("missing_env_vars", "")).strip()
        credentials_available = str(cred.get("credentials_available", "False")).lower() in {
            "1",
            "true",
            "yes",
            "y",
        }

        result: dict[str, Any] = {
            "priority": priority,
            "expected_input": expected_input,
            "source_family": source_family,
            "producer_script": producer_script,
            "endpoint_classification": endpoint_classification,
            "recommended_endpoint_action": recommended_action,
            "target_output_path": target_output_path,
            "required_env_vars": required_env_vars,
            "missing_env_vars": missing_env_vars,
            "credentials_available": credentials_available,
            "retry_attempted": False,
            "retry_status": "pending",
            "retry_command": "",
            "command_exit_code": "",
            "command_excerpt_safe": "",
            "row_count": 0,
            "sha256": "",
            "manifest_written": False,
            "validation_status": "",
            "failure_reason": "",
        }

        if any(contains_forbidden_token(piece) for piece in (expected_input, target_output_path)):
            forbidden_artifact_usage = True
            result["retry_status"] = "blocked_forbidden_artifact"
            result["failure_reason"] = "forbidden artifact token detected"
            results.append(result)
            still_blocked.append({**result, "review_status": "pending"})
            continue

        if not credentials_available:
            result["retry_status"] = "credential_missing"
            result["failure_reason"] = (
                f"missing credentials: {missing_env_vars}"
                if missing_env_vars
                else "credential check did not pass"
            )
            results.append(result)
            still_blocked.append({**result, "review_status": "pending_credentials"})
            continue

        command = str(
            row.get("safe_retry_command_if_available", "")
        ).strip() or SAFE_ENDPOINT_RETRY_COMMANDS.get(
            producer_script,
            "",
        )
        if not command:
            result["retry_status"] = "missing_retry_command"
            result["failure_reason"] = "no safe retry command available"
            results.append(result)
            still_blocked.append({**result, "review_status": "pending_command_mapping"})
            continue

        result["retry_attempted"] = True
        result["retry_command"] = command
        retries_attempted += 1

        ok, exit_code, excerpt = _run_command(root, command, timeout_s=command_timeout_s)
        result["command_exit_code"] = str(exit_code)
        result["command_excerpt_safe"] = excerpt
        if not ok:
            result["retry_status"] = "failed_command"
            result["failure_reason"] = excerpt or f"command failed ({exit_code})"
            results.append(result)
            still_blocked.append({**result, "review_status": "pending_retry"})
            continue

        valid, row_count, digest, reason = _validate_staged_output(
            root,
            target_output_path=target_output_path,
            required_columns_raw=required_columns,
        )
        result["row_count"] = row_count
        result["sha256"] = digest
        result["validation_status"] = "validated" if valid else "failed_validation"

        if not valid:
            result["retry_status"] = "failed_validation"
            result["failure_reason"] = reason
            results.append(result)
            still_blocked.append({**result, "review_status": "pending_validation_fix"})
            continue

        manifest = _write_manifest(
            root,
            phase_tag="endpoint",
            priority=priority,
            source_system=source_family or "endpoint_source",
            source_file=target_output_path,
            target_output_path=target_output_path,
            row_count=row_count,
            producer_script=producer_script,
            known_gaps="r4_8h_endpoint_retry",
        )
        new_manifests.append(manifest)

        retries_successful += 1
        result["manifest_written"] = True
        result["retry_status"] = "success"
        result["failure_reason"] = ""
        results.append(result)

    metrics = {
        "endpoint_retries_attempted": retries_attempted,
        "endpoint_retries_successful": retries_successful,
    }
    return results, still_blocked, new_manifests, metrics, forbidden_artifact_usage


def run_producer_patch_retries(
    root: Path,
    *,
    producer_rows: list[dict[str, str]],
    manual_rows_by_input: dict[str, dict[str, str]],
    command_timeout_s: int = 20,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, int], bool]:
    """Apply deterministic producer patch commands and run bounded retries."""

    root = Path(root)
    results: list[dict[str, Any]] = []
    still_blocked: list[dict[str, Any]] = []
    new_manifests: list[dict[str, Any]] = []
    forbidden_artifact_usage = False

    patches_applied = 0
    retries_attempted = 0
    retries_successful = 0

    for row in sorted(producer_rows, key=lambda item: safe_int(item.get("priority"))):
        priority = safe_int(row.get("priority"))
        expected_input = str(row.get("expected_input", "")).strip()
        source_family = str(row.get("source_family", "")).strip()
        producer_script = str(row.get("producer_script", "")).strip()
        failure_reason = str(row.get("failure_reason", "")).strip()
        patch_safe_now = str(row.get("patch_safe_now", "")).strip().lower() in {
            "1",
            "true",
            "yes",
            "y",
        }
        manual_source_required = str(row.get("manual_source_required", "")).strip().lower() in {
            "1",
            "true",
            "yes",
            "y",
        }

        manual_row = manual_rows_by_input.get(expected_input, {})
        target_output_path = str(
            manual_row.get("target_output_path") or row.get("target_output_path") or expected_input
        ).strip()
        required_columns = str(manual_row.get("required_columns", "")).strip()

        required_env_vars_list = _read_script_required_env_vars(root, producer_script)
        missing_env_vars_list = [
            name for name in required_env_vars_list if not str(os.getenv(name, "")).strip()
        ]

        result: dict[str, Any] = {
            "priority": priority,
            "expected_input": expected_input,
            "source_family": source_family,
            "producer_script": producer_script,
            "target_output_path": target_output_path,
            "patch_safe_now": patch_safe_now,
            "manual_source_required": manual_source_required,
            "deterministic_patch_applied": False,
            "required_env_vars": "|".join(required_env_vars_list),
            "missing_env_vars": "|".join(missing_env_vars_list),
            "retry_attempted": False,
            "retry_status": "pending",
            "retry_command": "",
            "command_exit_code": "",
            "command_excerpt_safe": "",
            "row_count": 0,
            "sha256": "",
            "manifest_written": False,
            "validation_status": "",
            "failure_reason": failure_reason,
        }

        if any(contains_forbidden_token(piece) for piece in (expected_input, target_output_path)):
            forbidden_artifact_usage = True
            result["retry_status"] = "blocked_forbidden_artifact"
            result["failure_reason"] = "forbidden artifact token detected"
            results.append(result)
            still_blocked.append({**result, "review_status": "pending"})
            continue

        if manual_source_required:
            result["retry_status"] = "manual_source_required"
            if not result["failure_reason"]:
                result["failure_reason"] = "manual source still required"
            results.append(result)
            still_blocked.append({**result, "review_status": "pending_manual_source"})
            continue

        if not patch_safe_now:
            result["retry_status"] = "patch_not_safe_now"
            if not result["failure_reason"]:
                result["failure_reason"] = "producer patch not marked safe now"
            results.append(result)
            still_blocked.append({**result, "review_status": "pending_patch_review"})
            continue

        if missing_env_vars_list:
            result["retry_status"] = "credential_missing"
            result["failure_reason"] = "missing credentials: " + "|".join(missing_env_vars_list)
            results.append(result)
            still_blocked.append({**result, "review_status": "pending_credentials"})
            continue

        command = SAFE_PRODUCER_RETRY_COMMANDS.get(producer_script, "")
        if not command:
            result["retry_status"] = "missing_retry_command"
            if not result["failure_reason"]:
                result["failure_reason"] = "no deterministic producer retry command available"
            results.append(result)
            still_blocked.append({**result, "review_status": "pending_command_mapping"})
            continue

        result["deterministic_patch_applied"] = True
        result["retry_command"] = command
        patches_applied += 1
        retries_attempted += 1
        result["retry_attempted"] = True

        ok, exit_code, excerpt = _run_command(root, command, timeout_s=command_timeout_s)
        result["command_exit_code"] = str(exit_code)
        result["command_excerpt_safe"] = excerpt
        if not ok:
            result["retry_status"] = "failed_command"
            result["failure_reason"] = excerpt or f"command failed ({exit_code})"
            results.append(result)
            still_blocked.append({**result, "review_status": "pending_retry"})
            continue

        valid, row_count, digest, reason = _validate_staged_output(
            root,
            target_output_path=target_output_path,
            required_columns_raw=required_columns,
        )
        result["row_count"] = row_count
        result["sha256"] = digest
        result["validation_status"] = "validated" if valid else "failed_validation"

        if not valid:
            result["retry_status"] = "failed_validation"
            result["failure_reason"] = reason
            results.append(result)
            still_blocked.append({**result, "review_status": "pending_validation_fix"})
            continue

        manifest = _write_manifest(
            root,
            phase_tag="producer",
            priority=priority,
            source_system=source_family or "producer_source",
            source_file=target_output_path,
            target_output_path=target_output_path,
            row_count=row_count,
            producer_script=producer_script,
            known_gaps="r4_8h_producer_retry",
        )
        new_manifests.append(manifest)

        retries_successful += 1
        result["manifest_written"] = True
        result["retry_status"] = "success"
        result["failure_reason"] = ""
        results.append(result)

    metrics = {
        "producer_patches_applied": patches_applied,
        "producer_retries_attempted": retries_attempted,
        "producer_retries_successful": retries_successful,
    }
    return results, still_blocked, new_manifests, metrics, forbidden_artifact_usage
