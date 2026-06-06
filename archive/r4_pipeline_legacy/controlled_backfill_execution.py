"""R4.8B controlled real backfill execution with explicit terminal statuses."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import subprocess
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

TERMINAL_SUCCESS = "success"
TERMINAL_CREDENTIAL_FAILURE = "credential_failure"
TERMINAL_NO_DATA = "no_data"
TERMINAL_SCHEMA_FAILURE = "schema_failure"
TERMINAL_MANUAL_FALLBACK = "manual_fallback_required"
TERMINAL_EXECUTION_FAILED = "execution_failed"
TERMINAL_EXECUTION_TIMEOUT = "execution_timeout"
TERMINAL_SKIPPED_NOT_READY = "skipped_not_ready"
TERMINAL_FORBIDDEN = "forbidden_artifact_input"
TERMINAL_PRODUCER_MISSING = "producer_script_missing"
TERMINAL_COMMAND_MISSING = "command_missing"


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _safe_int(raw: Any) -> int:
    try:
        return int(float(str(raw).strip()))
    except (TypeError, ValueError):
        return 0


def _to_bool(raw: Any) -> bool:
    return str(raw).strip().lower() in {"1", "true", "yes", "y"}


def _split_pipe(raw: Any) -> list[str]:
    return [part.strip() for part in str(raw or "").split("|") if part.strip()]


def _contains_forbidden_token(text: str) -> bool:
    lowered = str(text).lower()
    return any(token in lowered for token in FORBIDDEN_ARTIFACT_TOKENS)


def _sha256(path: Path) -> str:
    if not path.exists() or not path.is_file():
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _record_count(path: Path) -> int:
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


def _columns(path: Path) -> set[str]:
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


def _scan_script_env_vars(path: Path) -> list[str]:
    if not path.exists() or not path.is_file():
        return []
    text = path.read_text(encoding="utf-8", errors="replace")
    hits = set(re.findall(r"(?:os\.)?getenv\([\"']([A-Z0-9_]+)[\"']\)", text))
    hits.update(re.findall(r"os\.environ\[[\"']([A-Z0-9_]+)[\"']\]", text))
    return sorted(hits)


def _merge_env_vars(*raw_values: Any) -> list[str]:
    merged: set[str] = set()
    for raw in raw_values:
        merged.update(_split_pipe(raw))
    return sorted(merged)


def _run_shell_command(root: Path, command: str, timeout_s: int) -> tuple[bool, int, str]:
    if not command.strip():
        return False, 1, "missing command"

    try:
        completed = subprocess.run(
            command,
            shell=True,
            cwd=str(root),
            text=True,
            capture_output=True,
            timeout=timeout_s,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return False, 124, f"command timed out after {timeout_s}s"

    if completed.returncode == 0:
        return True, 0, ""

    reason = f"command failed with exit code {completed.returncode}"
    return False, int(completed.returncode), reason


def _validate_schema(path: Path, expected_schema_raw: str) -> tuple[bool, list[str], str]:
    required_cols = _split_pipe(expected_schema_raw)
    if not required_cols:
        return False, [], "expected schema missing"

    actual_cols = _columns(path)
    if not actual_cols:
        return False, required_cols, "unable to read output columns"

    missing = [col for col in required_cols if col not in actual_cols]
    if missing:
        return False, missing, "missing required columns"

    return True, [], ""


def _validate_with_command(root: Path, validation_command: str, timeout_s: int) -> tuple[bool, int, str]:
    if not validation_command.strip():
        return False, 1, "missing validation command"

    return _run_shell_command(root, validation_command, timeout_s)


def _manifest_relpath(priority: int, expected_input: str) -> str:
    stem = Path(expected_input).stem or "source"
    safe_stem = "".join(ch if ch.isalnum() else "_" for ch in stem).strip("_") or "source"
    return f"data/manifests/r4_8b/{priority:02d}_{safe_stem}.manifest.json"


def _write_validated_manifest(
    root: Path,
    *,
    priority: int,
    source_system: str,
    source_file: str,
    target_output_path: str,
    producer_script: str,
    row_count: int,
    schema_version: str,
    known_gaps: str,
) -> dict[str, Any]:
    target_abs = root / target_output_path
    manifest_payload = {
        "source_system": source_system,
        "source_file": source_file,
        "target_output_path": target_output_path,
        "row_count": int(row_count),
        "sha256": _sha256(target_abs),
        "generated_at": _utc_now(),
        "producer_script": producer_script,
        "validation_status": "validated",
        "schema_version": schema_version,
        "known_gaps": known_gaps,
        "manifest_type": "validated_source_manifest",
    }

    relpath = _manifest_relpath(priority, source_file)
    path = root / relpath
    _write_json(path, manifest_payload)

    inventory_row = dict(manifest_payload)
    inventory_row["manifest_path"] = relpath
    return inventory_row


def run_controlled_backfill_execution(
    root: Path,
    *,
    execute_downloads: bool = True,
    command_timeout_s: int = 120,
    validation_timeout_s: int = 60,
) -> dict[str, Any]:
    root = Path(root)
    exports_dir = root / "data" / "exports"
    review_dir = root / "data" / "review_queue"

    readiness_rows = _read_csv(exports_dir / "backfill_readiness_matrix_r4_8a.csv")
    readiness_status = _read_json(exports_dir / "backfill_readiness_status_r4_8a.json")
    controlled_plan = _read_json(exports_dir / "controlled_backfill_plan_r4_8.json")
    controlled_manifest = _read_csv(exports_dir / "controlled_backfill_manifest_r4_8.csv")
    runner_manifest = _read_csv(exports_dir / "backfill_runner_manifest_r4_7.csv")
    r46_plan = _read_csv(exports_dir / "backfill_execution_plan_r4_6.csv")
    rebuild_status = _read_json(exports_dir / "rebuild_status.json")

    row_fabrication_policy = str(
        rebuild_status.get("row_fabrication_policy")
        or readiness_status.get("row_fabrication_policy")
        or controlled_plan.get("row_fabrication_policy")
        or "FORBIDDEN_NO_SYNTHETIC_ROWS"
    )

    runner_by_expected = {
        str(row.get("expected_input", "")).strip(): row
        for row in runner_manifest
        if str(row.get("expected_input", "")).strip()
    }
    controlled_by_expected = {
        str(row.get("expected_input", "")).strip(): row
        for row in controlled_manifest
        if str(row.get("expected_input", "")).strip()
    }
    r46_by_expected = {
        str(row.get("expected_input", "")).strip(): row
        for row in r46_plan
        if str(row.get("expected_input", "")).strip()
    }

    results_rows: list[dict[str, Any]] = []
    failures_rows: list[dict[str, Any]] = []
    no_data_rows: list[dict[str, Any]] = []
    schema_failure_rows: list[dict[str, Any]] = []
    manual_fallback_rows: list[dict[str, Any]] = []
    credential_failure_rows: list[dict[str, Any]] = []
    validated_manifest_rows: list[dict[str, Any]] = []

    forbidden_artifact_usage = False
    rows_ingested = 0
    production_inputs_staged = 0

    for row in sorted(readiness_rows, key=lambda r: _safe_int(r.get("priority"))):
        priority = _safe_int(row.get("priority"))
        expected_input = str(row.get("expected_input", "")).strip()
        source_family = str(row.get("source_family", "")).strip()
        readiness = str(row.get("readiness", "")).strip() or "blocked_unknown"
        target_output_path = str(row.get("target_output_path") or expected_input).strip()

        runner_row = runner_by_expected.get(expected_input, {})
        controlled_row = controlled_by_expected.get(expected_input, {})
        r46_row = r46_by_expected.get(expected_input, {})

        producer_script = str(
            row.get("producer_script")
            or runner_row.get("likely_producer_script")
            or ""
        ).strip()
        producer_script_exists = bool(producer_script and (root / producer_script).exists())

        command = str(runner_row.get("real_run_command_template") or runner_row.get("automated_command") or "").strip()
        validation_command = str(runner_row.get("validation_command") or row.get("validation_command") or "").strip()
        expected_schema = str(runner_row.get("expected_schema") or "").strip()

        merged_env_vars = _merge_env_vars(
            row.get("required_env_vars", ""),
            runner_row.get("required_env_vars", ""),
        )
        if producer_script:
            merged_env_vars = sorted(set(merged_env_vars + _scan_script_env_vars(root / producer_script)))
        missing_env_vars = [name for name in merged_env_vars if not os.getenv(name)]

        manifest_path = _manifest_relpath(priority, expected_input)

        has_forbidden = any(
            _contains_forbidden_token(candidate)
            for candidate in [expected_input, target_output_path, manifest_path]
            if candidate
        )

        forbidden_artifact_usage = bool(forbidden_artifact_usage or has_forbidden)

        attempted = False
        skipped_reason = ""
        command_executed = False
        command_exit_code = ""
        validation_executed = False
        validation_exit_code = ""

        terminal_status = TERMINAL_MANUAL_FALLBACK
        blocker_reason = ""
        next_action = ""
        row_count = 0
        schema_valid = False
        schema_missing_columns = ""
        validation_status = "not_run"
        validated_manifest_written = False
        output_exists = False
        output_sha256 = ""

        target_output_abs = root / target_output_path
        pre_hash = _sha256(target_output_abs)

        if has_forbidden:
            terminal_status = TERMINAL_FORBIDDEN
            blocker_reason = "forbidden artifact token detected"
            skipped_reason = blocker_reason
            next_action = "replace source path with an allowed raw/staging source path"

        elif readiness != "ready_for_execute_downloads":
            terminal_status = TERMINAL_SKIPPED_NOT_READY
            blocker_reason = f"source readiness is {readiness}"
            skipped_reason = blocker_reason
            next_action = str(row.get("next_action", "")).strip() or "resolve readiness blocker and rerun"

        elif merged_env_vars and missing_env_vars:
            terminal_status = TERMINAL_CREDENTIAL_FAILURE
            blocker_reason = "missing required credentials"
            skipped_reason = blocker_reason
            next_action = "set required env vars and rerun R4.8B"

        elif not producer_script or not producer_script_exists:
            terminal_status = TERMINAL_PRODUCER_MISSING
            blocker_reason = "producer script missing"
            skipped_reason = blocker_reason
            next_action = "add/repair producer script and rerun R4.8B"

        elif not command:
            terminal_status = TERMINAL_COMMAND_MISSING
            blocker_reason = "no execution command available"
            skipped_reason = blocker_reason
            next_action = "define real_run_command_template and rerun R4.8B"

        elif not execute_downloads:
            terminal_status = TERMINAL_SKIPPED_NOT_READY
            blocker_reason = "execute_downloads disabled for this run"
            skipped_reason = blocker_reason
            next_action = "rerun with execute_downloads enabled"

        else:
            attempted = True
            command_executed = True
            ok, exit_code, exec_reason = _run_shell_command(root, command, command_timeout_s)
            command_exit_code = str(exit_code)

            if not ok and exit_code == 124:
                terminal_status = TERMINAL_EXECUTION_TIMEOUT
                blocker_reason = exec_reason
                next_action = "retry source with longer timeout or manual import"
            elif not ok:
                terminal_status = TERMINAL_EXECUTION_FAILED
                blocker_reason = exec_reason
                next_action = "inspect producer script output and retry or use manual fallback"
            else:
                output_exists = target_output_abs.exists() and target_output_abs.is_file()
                row_count = _record_count(target_output_abs)

                if not output_exists:
                    terminal_status = TERMINAL_NO_DATA
                    blocker_reason = "target output not produced"
                    next_action = "verify producer output mapping and retry or manual import"
                elif row_count <= 0:
                    terminal_status = TERMINAL_NO_DATA
                    blocker_reason = "source produced zero rows"
                    next_action = "backfill source date scope or use manual export"
                else:
                    schema_valid, missing_cols, schema_reason = _validate_schema(target_output_abs, expected_schema)
                    schema_missing_columns = "|".join(missing_cols)
                    if not schema_valid:
                        terminal_status = TERMINAL_SCHEMA_FAILURE
                        blocker_reason = schema_reason
                        next_action = "repair schema mapping/normalization for this source"
                    else:
                        validation_executed = bool(validation_command)
                        if validation_command:
                            valid_ok, valid_exit, valid_reason = _validate_with_command(
                                root,
                                validation_command,
                                validation_timeout_s,
                            )
                            validation_exit_code = str(valid_exit)
                            if not valid_ok:
                                terminal_status = TERMINAL_SCHEMA_FAILURE
                                blocker_reason = f"validation command failed: {valid_reason}"
                                validation_status = "failed"
                                next_action = "fix validation blockers and rerun source"
                            else:
                                validation_status = "passed"

                        if terminal_status not in {TERMINAL_SCHEMA_FAILURE}:
                            terminal_status = TERMINAL_SUCCESS
                            blocker_reason = ""
                            next_action = "source staged with validated manifest"
                            output_sha256 = _sha256(target_output_abs)
                            rows_ingested += row_count
                            production_inputs_staged += 1

                            acceptance_gate = str(r46_row.get("acceptance_gate", "")).strip() or str(
                                controlled_row.get("expected_acceptance_gate", "")
                            ).strip()
                            known_gaps = ""
                            if acceptance_gate:
                                known_gaps = f"acceptance_gate={acceptance_gate}"

                            validated_manifest_rows.append(
                                _write_validated_manifest(
                                    root,
                                    priority=priority,
                                    source_system=source_family,
                                    source_file=expected_input,
                                    target_output_path=target_output_path,
                                    producer_script=producer_script,
                                    row_count=row_count,
                                    schema_version="r4_8b_schema_v1",
                                    known_gaps=known_gaps,
                                )
                            )
                            validated_manifest_written = True

        if terminal_status == TERMINAL_NO_DATA:
            no_data_rows.append(
                {
                    "priority": priority,
                    "expected_input": expected_input,
                    "source_family": source_family,
                    "target_output_path": target_output_path,
                    "reason": blocker_reason,
                    "next_action": next_action,
                }
            )

        if terminal_status == TERMINAL_SCHEMA_FAILURE:
            schema_failure_rows.append(
                {
                    "priority": priority,
                    "expected_input": expected_input,
                    "source_family": source_family,
                    "target_output_path": target_output_path,
                    "expected_schema": expected_schema,
                    "missing_columns": schema_missing_columns,
                    "validation_exit_code": validation_exit_code,
                    "reason": blocker_reason,
                    "next_action": next_action,
                }
            )

        if terminal_status == TERMINAL_CREDENTIAL_FAILURE:
            credential_failure_rows.append(
                {
                    "priority": priority,
                    "expected_input": expected_input,
                    "source_family": source_family,
                    "producer_script": producer_script,
                    "required_env_vars": "|".join(merged_env_vars),
                    "missing_env_vars": "|".join(missing_env_vars),
                    "reason": blocker_reason,
                    "next_action": next_action,
                }
            )

        if terminal_status != TERMINAL_SUCCESS:
            failures_rows.append(
                {
                    "priority": priority,
                    "expected_input": expected_input,
                    "source_family": source_family,
                    "terminal_status": terminal_status,
                    "reason": blocker_reason,
                    "attempted": attempted,
                    "command_executed": command_executed,
                    "command_exit_code": command_exit_code,
                    "next_action": next_action,
                }
            )

        if terminal_status != TERMINAL_SUCCESS:
            manual_fallback_rows.append(
                {
                    "priority": priority,
                    "expected_input": expected_input,
                    "source_family": source_family,
                    "terminal_status": terminal_status,
                    "reason": blocker_reason,
                    "next_action": next_action,
                }
            )

        post_hash = _sha256(target_output_abs)
        output_exists = target_output_abs.exists() and target_output_abs.is_file()

        results_rows.append(
            {
                "priority": priority,
                "expected_input": expected_input,
                "source_family": source_family,
                "readiness": readiness,
                "terminal_status": terminal_status,
                "attempted": attempted,
                "skipped_reason": skipped_reason,
                "target_output_path": target_output_path,
                "producer_script": producer_script,
                "command": command,
                "command_executed": command_executed,
                "command_exit_code": command_exit_code,
                "required_env_vars": "|".join(merged_env_vars),
                "missing_env_vars": "|".join(missing_env_vars),
                "output_exists": output_exists,
                "row_count": row_count,
                "schema_valid": schema_valid,
                "validation_command": validation_command,
                "validation_executed": validation_executed,
                "validation_exit_code": validation_exit_code,
                "validated_manifest_path": manifest_path if validated_manifest_written else "",
                "validated_manifest_written": validated_manifest_written,
                "blocker_reason": blocker_reason,
                "next_action": next_action,
                "forbidden_artifact_usage": has_forbidden,
                "target_hash_before": pre_hash,
                "target_hash_after": post_hash,
                "target_changed": bool(pre_hash != post_hash and post_hash),
                "target_sha256": output_sha256 or post_hash,
            }
        )

    total_sources = len(readiness_rows)
    attempted_sources = sum(1 for row in results_rows if _to_bool(row.get("attempted")))
    successful_sources = sum(1 for row in results_rows if row.get("terminal_status") == TERMINAL_SUCCESS)
    no_data_sources = len(no_data_rows)
    credential_failures = len(credential_failure_rows)
    schema_failures = len(schema_failure_rows)
    manual_fallback_required = len(manual_fallback_rows)
    failed_sources = total_sources - successful_sources
    validated_source_manifests_written = len(validated_manifest_rows)

    staged_inputs = [row for row in results_rows if row.get("terminal_status") == TERMINAL_SUCCESS]
    staged_with_manifest = [row for row in staged_inputs if _to_bool(row.get("validated_manifest_written"))]

    all_terminal = all(str(row.get("terminal_status", "")).strip() for row in results_rows)
    all_attempted_or_skipped = all(
        _to_bool(row.get("attempted")) or str(row.get("skipped_reason", "")).strip() for row in results_rows
    )

    phase_7_8_blocked = True

    r4_8b_gate_passed = bool(
        total_sources > 0
        and all_terminal
        and all_attempted_or_skipped
        and len(results_rows) == total_sources
        and not forbidden_artifact_usage
        and row_fabrication_policy == "FORBIDDEN_NO_SYNTHETIC_ROWS"
        and len(staged_inputs) == len(staged_with_manifest)
        and phase_7_8_blocked
    )

    _write_csv(
        exports_dir / "controlled_backfill_execution_results_r4_8b.csv",
        results_rows,
        [
            "priority",
            "expected_input",
            "source_family",
            "readiness",
            "terminal_status",
            "attempted",
            "skipped_reason",
            "target_output_path",
            "producer_script",
            "command",
            "command_executed",
            "command_exit_code",
            "required_env_vars",
            "missing_env_vars",
            "output_exists",
            "row_count",
            "schema_valid",
            "validation_command",
            "validation_executed",
            "validation_exit_code",
            "validated_manifest_path",
            "validated_manifest_written",
            "blocker_reason",
            "next_action",
            "forbidden_artifact_usage",
            "target_hash_before",
            "target_hash_after",
            "target_changed",
            "target_sha256",
        ],
    )

    _write_csv(
        exports_dir / "validated_source_manifest_inventory_r4_8b.csv",
        validated_manifest_rows,
        [
            "source_system",
            "source_file",
            "target_output_path",
            "row_count",
            "sha256",
            "generated_at",
            "producer_script",
            "validation_status",
            "schema_version",
            "known_gaps",
            "manifest_type",
            "manifest_path",
        ],
    )

    _write_csv(
        review_dir / "controlled_backfill_execution_failures_r4_8b.csv",
        failures_rows,
        [
            "priority",
            "expected_input",
            "source_family",
            "terminal_status",
            "reason",
            "attempted",
            "command_executed",
            "command_exit_code",
            "next_action",
        ],
    )

    _write_csv(
        review_dir / "no_data_sources_r4_8b.csv",
        no_data_rows,
        [
            "priority",
            "expected_input",
            "source_family",
            "target_output_path",
            "reason",
            "next_action",
        ],
    )

    _write_csv(
        review_dir / "schema_failures_r4_8b.csv",
        schema_failure_rows,
        [
            "priority",
            "expected_input",
            "source_family",
            "target_output_path",
            "expected_schema",
            "missing_columns",
            "validation_exit_code",
            "reason",
            "next_action",
        ],
    )

    _write_csv(
        review_dir / "manual_fallback_required_r4_8b.csv",
        manual_fallback_rows,
        [
            "priority",
            "expected_input",
            "source_family",
            "terminal_status",
            "reason",
            "next_action",
        ],
    )

    _write_csv(
        review_dir / "credential_failures_r4_8b.csv",
        credential_failure_rows,
        [
            "priority",
            "expected_input",
            "source_family",
            "producer_script",
            "required_env_vars",
            "missing_env_vars",
            "reason",
            "next_action",
        ],
    )

    status_payload = {
        "generated_at": _utc_now(),
        "r4_8b_phase_type": "CONTROLLED_REAL_BACKFILL_EXECUTION",
        "r4_8b_execute_downloads_requested": bool(execute_downloads),
        "r4_8b_gate_passed": r4_8b_gate_passed,
        "r4_8b_total_sources": total_sources,
        "r4_8b_attempted_sources": attempted_sources,
        "r4_8b_successful_sources": successful_sources,
        "r4_8b_failed_sources": failed_sources,
        "r4_8b_no_data_sources": no_data_sources,
        "r4_8b_credential_failures": credential_failures,
        "r4_8b_schema_failures": schema_failures,
        "r4_8b_manual_fallback_required": manual_fallback_required,
        "r4_8b_rows_ingested": rows_ingested,
        "r4_8b_production_inputs_staged": production_inputs_staged,
        "r4_8b_validated_source_manifests_written": validated_source_manifests_written,
        "r4_8b_forbidden_artifact_usage": forbidden_artifact_usage,
        "r4_8b_downloads_executed": bool(execute_downloads and attempted_sources > 0),
        "row_fabrication_policy": row_fabrication_policy,
        "phase_7_8_blocked": phase_7_8_blocked,
        "inputs": {
            "backfill_readiness_matrix": "data/exports/backfill_readiness_matrix_r4_8a.csv",
            "backfill_readiness_status": "data/exports/backfill_readiness_status_r4_8a.json",
            "controlled_backfill_plan": "data/exports/controlled_backfill_plan_r4_8.json",
            "controlled_backfill_manifest": "data/exports/controlled_backfill_manifest_r4_8.csv",
            "backfill_runner_manifest": "data/exports/backfill_runner_manifest_r4_7.csv",
            "backfill_execution_plan": "data/exports/backfill_execution_plan_r4_6.csv",
        },
        "outputs": {
            "execution_results": "data/exports/controlled_backfill_execution_results_r4_8b.csv",
            "execution_status": "data/exports/controlled_backfill_execution_status_r4_8b.json",
            "validated_source_manifest_inventory": "data/exports/validated_source_manifest_inventory_r4_8b.csv",
            "execution_failures": "data/review_queue/controlled_backfill_execution_failures_r4_8b.csv",
            "no_data_sources": "data/review_queue/no_data_sources_r4_8b.csv",
            "schema_failures": "data/review_queue/schema_failures_r4_8b.csv",
            "manual_fallback_required": "data/review_queue/manual_fallback_required_r4_8b.csv",
            "credential_failures": "data/review_queue/credential_failures_r4_8b.csv",
        },
    }

    _write_json(exports_dir / "controlled_backfill_execution_status_r4_8b.json", status_payload)

    next_rebuild_status = dict(rebuild_status)
    next_rebuild_status.update(
        {
            "r4_8b_generated_at": status_payload["generated_at"],
            "r4_8b_phase_type": status_payload["r4_8b_phase_type"],
            "r4_8b_gate_passed": status_payload["r4_8b_gate_passed"],
            "r4_8b_total_sources": status_payload["r4_8b_total_sources"],
            "r4_8b_attempted_sources": status_payload["r4_8b_attempted_sources"],
            "r4_8b_successful_sources": status_payload["r4_8b_successful_sources"],
            "r4_8b_failed_sources": status_payload["r4_8b_failed_sources"],
            "r4_8b_no_data_sources": status_payload["r4_8b_no_data_sources"],
            "r4_8b_credential_failures": status_payload["r4_8b_credential_failures"],
            "r4_8b_schema_failures": status_payload["r4_8b_schema_failures"],
            "r4_8b_manual_fallback_required": status_payload["r4_8b_manual_fallback_required"],
            "r4_8b_rows_ingested": status_payload["r4_8b_rows_ingested"],
            "r4_8b_production_inputs_staged": status_payload["r4_8b_production_inputs_staged"],
            "r4_8b_validated_source_manifests_written": status_payload[
                "r4_8b_validated_source_manifests_written"
            ],
            "r4_8b_forbidden_artifact_usage": status_payload["r4_8b_forbidden_artifact_usage"],
            "r4_8b_downloads_executed": status_payload["r4_8b_downloads_executed"],
            "row_fabrication_policy": row_fabrication_policy,
            "phase_7_8_blocked": True,
            "r4_8b_outputs": status_payload["outputs"],
        }
    )
    _write_json(exports_dir / "rebuild_status.json", next_rebuild_status)

    return status_payload
