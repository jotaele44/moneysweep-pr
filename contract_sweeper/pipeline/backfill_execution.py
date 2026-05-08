"""R4.8 controlled backfill execution and manual import validation.

This phase consumes R4.7 runner manifests and can optionally execute producer
commands when explicitly requested. Default mode is dry-run planning plus output
validation; no downloads are executed unless execute_downloads is enabled.
"""

from __future__ import annotations

import csv
import fnmatch
import json
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
    "investigative",
)


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


def _split_pipe(raw: str) -> list[str]:
    return [part.strip() for part in str(raw or "").split("|") if part.strip()]


def _contains_forbidden_token(text: str) -> bool:
    lowered = str(text).lower()
    return any(token in lowered for token in FORBIDDEN_ARTIFACT_TOKENS)


def _safe_int(raw: Any) -> int:
    try:
        return int(float(str(raw).strip()))
    except (TypeError, ValueError):
        return 0


def _read_table(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(path, dtype=str, low_memory=False)
    if suffix == ".parquet":
        return pd.read_parquet(path)
    raise ValueError(f"unsupported table format: {path}")


def _validate_table(path: Path, required_columns: list[str]) -> tuple[bool, int, str, list[str]]:
    if not path.exists():
        return False, 0, "missing_output", required_columns

    try:
        df = _read_table(path)
    except Exception as exc:  # pragma: no cover - defensive branch
        return False, 0, f"read_failure:{exc}", required_columns

    row_count = int(len(df.index))
    if row_count <= 0:
        return False, row_count, "empty_output", required_columns

    if required_columns:
        current = {str(col) for col in df.columns}
        missing = [col for col in required_columns if col not in current]
        if missing:
            return False, row_count, "missing_required_columns", missing

    return True, row_count, "ok", []


def _should_execute(*, dry_run: bool, execute_downloads: bool, classification: str) -> bool:
    return bool((not dry_run) and execute_downloads and classification == "automated_backfill_available")


def _run_command(root: Path, command: str) -> tuple[int, str]:
    if not command:
        return 1, "missing command"
    completed = subprocess.run(
        command,
        shell=True,
        cwd=str(root),
        text=True,
        capture_output=True,
        timeout=1800,
        check=False,
    )
    output = (completed.stdout or "") + ("\n" + completed.stderr if completed.stderr else "")
    return int(completed.returncode), output.strip()[:4000]


def _slot_matches_pattern(path: Path, patterns: list[str]) -> bool:
    if not patterns:
        return True
    return any(fnmatch.fnmatch(path.name, pat) for pat in patterns)


def _validate_manual_slot(root: Path, slot: dict[str, str]) -> dict[str, Any]:
    slot_id = str(slot.get("slot_id", ""))
    expected_input = str(slot.get("expected_input", ""))
    dropzone_rel = str(slot.get("dropzone_path", ""))
    dropzone_path = root / dropzone_rel
    required_columns = _split_pipe(slot.get("required_columns", ""))
    accepted_patterns = _split_pipe(slot.get("accepted_file_patterns", ""))

    if not dropzone_rel:
        return {
            "slot_id": slot_id,
            "expected_input": expected_input,
            "dropzone_path": dropzone_rel,
            "slot_status": "invalid_slot_definition",
            "validation_passed": False,
            "row_count": 0,
            "missing_columns": "",
            "reason": "missing dropzone_path",
        }

    if not dropzone_path.exists():
        return {
            "slot_id": slot_id,
            "expected_input": expected_input,
            "dropzone_path": dropzone_rel,
            "slot_status": "pending_manual_file",
            "validation_passed": False,
            "row_count": 0,
            "missing_columns": "",
            "reason": "dropzone file not found",
        }

    if accepted_patterns and not _slot_matches_pattern(dropzone_path, accepted_patterns):
        return {
            "slot_id": slot_id,
            "expected_input": expected_input,
            "dropzone_path": dropzone_rel,
            "slot_status": "pattern_mismatch",
            "validation_passed": False,
            "row_count": 0,
            "missing_columns": "",
            "reason": "dropzone file does not match accepted patterns",
        }

    passed, row_count, reason, missing = _validate_table(dropzone_path, required_columns)
    return {
        "slot_id": slot_id,
        "expected_input": expected_input,
        "dropzone_path": dropzone_rel,
        "slot_status": "ready_for_import" if passed else "failed_validation",
        "validation_passed": passed,
        "row_count": row_count,
        "missing_columns": "|".join(missing),
        "reason": reason,
    }


def run_backfill_execution(
    root: Path,
    *,
    dry_run: bool = True,
    execute_downloads: bool = False,
    validate_manual_slots: bool = True,
) -> dict[str, Any]:
    root = Path(root)
    exports_dir = root / "data" / "exports"
    review_dir = root / "data" / "review_queue"

    runner_plan = _read_json(exports_dir / "backfill_runner_plan_r4_7.json")
    runner_manifest_rows = _read_csv(exports_dir / "backfill_runner_manifest_r4_7.csv")
    manual_slots = _read_csv(exports_dir / "import_slots_r4_7.csv")
    prior_rebuild = _read_json(exports_dir / "rebuild_status.json")

    row_fabrication_policy = str(
        prior_rebuild.get("row_fabrication_policy")
        or runner_plan.get("row_fabrication_policy")
        or "FORBIDDEN_NO_SYNTHETIC_ROWS"
    )

    execution_rows: list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = []

    executed_commands = 0
    successful_commands = 0
    rows_ingested_during_run = 0
    rows_observed_valid_outputs = 0

    forbidden_artifact_usage = False

    for row in sorted(runner_manifest_rows, key=lambda r: _safe_int(r.get("priority"))):
        priority = _safe_int(row.get("priority"))
        classification = str(row.get("classification", ""))
        expected_input = str(row.get("expected_input", ""))
        source_family = str(row.get("source_family", ""))
        target_output_path = str(row.get("target_output_path") or expected_input)
        required_columns = _split_pipe(row.get("expected_schema", ""))

        if _contains_forbidden_token(expected_input) or _contains_forbidden_token(target_output_path):
            forbidden_artifact_usage = True

        execute_now = _should_execute(
            dry_run=dry_run,
            execute_downloads=execute_downloads,
            classification=classification,
        )

        command_mode = "dry_run_plan"
        command_selected = str(row.get("dry_run_command", ""))
        command_exit_code = None
        command_output_excerpt = ""

        if execute_now:
            command_mode = "execute"
            command_selected = str(row.get("real_run_command_template", ""))
            executed_commands += 1
            command_exit_code, command_output_excerpt = _run_command(root, command_selected)
            if command_exit_code == 0:
                successful_commands += 1

        output_abs = root / target_output_path
        validation_passed, row_count, validation_reason, missing_columns = _validate_table(output_abs, required_columns)
        if execute_now and command_exit_code == 0 and validation_passed:
            rows_ingested_during_run += row_count
        if validation_passed:
            rows_observed_valid_outputs += row_count

        row_status = {
            "priority": priority,
            "classification": classification,
            "source_family": source_family,
            "expected_input": expected_input,
            "target_output_path": target_output_path,
            "command_mode": command_mode,
            "command_selected": command_selected,
            "command_executed": execute_now,
            "command_exit_code": "" if command_exit_code is None else str(command_exit_code),
            "validation_passed": validation_passed,
            "validation_reason": validation_reason,
            "row_count": row_count,
            "missing_columns": "|".join(missing_columns),
            "blocker_reason": str(row.get("blocker_reason", "")),
        }

        if command_output_excerpt:
            row_status["command_output_excerpt"] = command_output_excerpt
        else:
            row_status["command_output_excerpt"] = ""

        execution_rows.append(row_status)

        if (not validation_passed) or str(row.get("blocker_reason", "")):
            blockers.append(
                {
                    "priority": priority,
                    "expected_input": expected_input,
                    "classification": classification,
                    "target_output_path": target_output_path,
                    "blocker_reason": str(row.get("blocker_reason", "")) or validation_reason,
                }
            )

    manual_validation_rows: list[dict[str, Any]] = []
    if validate_manual_slots and manual_slots:
        manual_validation_rows = [_validate_manual_slot(root, slot) for slot in manual_slots]

    manual_failures = [row for row in manual_validation_rows if not row.get("validation_passed")]

    total_sources = len(execution_rows)
    validated_sources = sum(1 for row in execution_rows if bool(row.get("validation_passed")))
    failed_sources = total_sources - validated_sources

    manual_slots_total = len(manual_validation_rows)
    manual_slots_ready = sum(1 for row in manual_validation_rows if row.get("slot_status") == "ready_for_import")
    manual_slots_missing = sum(1 for row in manual_validation_rows if row.get("slot_status") == "pending_manual_file")

    manual_slots_gate_passed = (manual_slots_total == 0) or (manual_slots_ready == manual_slots_total)

    r4_8_gate_passed = bool(
        total_sources > 0
        and failed_sources == 0
        and not forbidden_artifact_usage
        and manual_slots_gate_passed
    )

    phase_7_8_blocked = True
    phase_7_8_block_reason = (
        "Phase 7/8 remains blocked until R5/R6/R7 gates pass; "
        "R4.8 only executes controlled backfill and manual import validation."
    )

    _write_csv(
        exports_dir / "backfill_execution_results_r4_8.csv",
        execution_rows,
        [
            "priority",
            "classification",
            "source_family",
            "expected_input",
            "target_output_path",
            "command_mode",
            "command_selected",
            "command_executed",
            "command_exit_code",
            "validation_passed",
            "validation_reason",
            "row_count",
            "missing_columns",
            "blocker_reason",
            "command_output_excerpt",
        ],
    )

    _write_csv(
        exports_dir / "manual_import_validation_r4_8.csv",
        manual_validation_rows,
        [
            "slot_id",
            "expected_input",
            "dropzone_path",
            "slot_status",
            "validation_passed",
            "row_count",
            "missing_columns",
            "reason",
        ],
    )

    _write_csv(
        review_dir / "backfill_execution_blockers_r4_8.csv",
        blockers,
        ["priority", "expected_input", "classification", "target_output_path", "blocker_reason"],
    )

    _write_csv(
        review_dir / "manual_import_validation_failures_r4_8.csv",
        manual_failures,
        [
            "slot_id",
            "expected_input",
            "dropzone_path",
            "slot_status",
            "validation_passed",
            "row_count",
            "missing_columns",
            "reason",
        ],
    )

    status = {
        "generated_at": _utc_now(),
        "r4_8_phase_type": "CONTROLLED_BACKFILL_EXECUTION_AND_MANUAL_IMPORT_VALIDATION",
        "r4_8_gate_passed": r4_8_gate_passed,
        "dry_run": bool(dry_run),
        "execute_downloads_requested": bool(execute_downloads),
        "r4_8_execute_downloads_default": False,
        "r4_8_downloads_executed": bool(executed_commands > 0),
        "r4_8_executed_download_commands": executed_commands,
        "r4_8_successful_download_commands": successful_commands,
        "r4_8_total_sources": total_sources,
        "r4_8_validated_sources": validated_sources,
        "r4_8_failed_sources": failed_sources,
        "r4_8_manual_slots_total": manual_slots_total,
        "r4_8_manual_slots_ready": manual_slots_ready,
        "r4_8_manual_slots_missing": manual_slots_missing,
        "r4_8_rows_ingested_during_run": rows_ingested_during_run,
        "r4_8_rows_observed_valid_outputs": rows_observed_valid_outputs,
        "row_fabrication_policy": row_fabrication_policy,
        "forbidden_artifact_usage": forbidden_artifact_usage,
        "phase_7_8_blocked": phase_7_8_blocked,
        "phase_7_8_block_reason": phase_7_8_block_reason,
        "outputs": {
            "backfill_execution_results": "data/exports/backfill_execution_results_r4_8.csv",
            "manual_import_validation": "data/exports/manual_import_validation_r4_8.csv",
            "backfill_execution_blockers": "data/review_queue/backfill_execution_blockers_r4_8.csv",
            "manual_import_validation_failures": "data/review_queue/manual_import_validation_failures_r4_8.csv",
        },
    }
    _write_json(exports_dir / "backfill_execution_status_r4_8.json", status)

    rebuild_status = dict(prior_rebuild)
    rebuild_status.update(
        {
            "r4_8_generated_at": status["generated_at"],
            "r4_8_phase_type": status["r4_8_phase_type"],
            "r4_8_gate_passed": r4_8_gate_passed,
            "r4_8_execute_downloads_default": False,
            "r4_8_execute_downloads_requested": bool(execute_downloads),
            "r4_8_downloads_executed": bool(executed_commands > 0),
            "r4_8_executed_download_commands": executed_commands,
            "r4_8_successful_download_commands": successful_commands,
            "r4_8_total_sources": total_sources,
            "r4_8_validated_sources": validated_sources,
            "r4_8_failed_sources": failed_sources,
            "r4_8_manual_slots_total": manual_slots_total,
            "r4_8_manual_slots_ready": manual_slots_ready,
            "r4_8_manual_slots_missing": manual_slots_missing,
            "r4_8_rows_ingested_during_run": rows_ingested_during_run,
            "r4_8_rows_observed_valid_outputs": rows_observed_valid_outputs,
            "row_fabrication_policy": row_fabrication_policy,
            "phase_7_8_blocked": phase_7_8_blocked,
            "phase_7_8_block_reason": phase_7_8_block_reason,
            "r4_8_outputs": status["outputs"],
        }
    )
    _write_json(exports_dir / "rebuild_status.json", rebuild_status)

    return status
