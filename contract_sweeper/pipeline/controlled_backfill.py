"""R4.8 controlled backfill execution and manual import validation orchestration."""

from __future__ import annotations

import csv
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from contract_sweeper.pipeline.manual_import_validation import (
    build_manual_import_slots,
    validate_manual_import_slots,
    write_manual_import_csv,
)
from contract_sweeper.pipeline.source_manifest_writer import write_source_manifest_inventory

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


def _to_bool(raw: Any) -> bool:
    return str(raw).strip().lower() in {"1", "true", "yes", "y"}


def _safe_int(raw: Any) -> int:
    try:
        return int(float(str(raw).strip()))
    except (TypeError, ValueError):
        return 0


def _schema_version_for(row: dict[str, Any]) -> str:
    # Keep schema version deterministic without adding new dependencies.
    schema = str(row.get("expected_schema", ""))
    return "r4_8_schema_v1" if schema else "r4_8_schema_unknown"


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


def _classify_source_task(
    row: dict[str, Any],
    *,
    execute_downloads: bool,
) -> tuple[str, list[str], str, bool, bool, bool, bool]:
    """Return (classification, missing_env_vars, blocker_reason, forbidden, has_schema, has_automated_path, manual_required)."""

    expected_input = str(row.get("expected_input", ""))
    target_output_path = str(row.get("target_output_path") or expected_input)
    expected_schema = _split_pipe(row.get("expected_schema", ""))

    has_forbidden = _contains_forbidden_token(expected_input) or _contains_forbidden_token(target_output_path)
    has_schema = bool(expected_schema)

    real_command = str(row.get("real_run_command_template") or row.get("automated_command") or "").strip()
    has_automated_path = bool(real_command)

    requires_manual_export = _to_bool(row.get("requires_manual_export"))
    manual_flag = str(row.get("classification", "")).strip() == "manual_import_required"
    manual_required = bool(manual_flag or (requires_manual_export and not has_automated_path))

    if has_forbidden:
        return "blocked", [], "forbidden artifact token detected", True, has_schema, has_automated_path, manual_required

    if not has_schema:
        return "missing_schema", [], "expected schema unresolved", False, has_schema, has_automated_path, manual_required

    if manual_required:
        return "manual_import_required", [], "manual import path required", False, has_schema, has_automated_path, manual_required

    if has_automated_path:
        required_env_vars = _split_pipe(row.get("required_env_vars", ""))
        missing_env_vars = [env for env in required_env_vars if not os.getenv(env)]
        if missing_env_vars:
            return "missing_credentials", missing_env_vars, "missing required credentials", False, has_schema, has_automated_path, manual_required

        if execute_downloads:
            return "executable_with_credentials", [], "", False, has_schema, has_automated_path, manual_required

        return "dry_run_ready", [], "dry-run default mode", False, has_schema, has_automated_path, manual_required

    return "blocked", [], "no automated command and no manual import path", False, has_schema, has_automated_path, manual_required


def run_controlled_backfill(
    root: Path,
    *,
    dry_run: bool = True,
    execute_downloads: bool = False,
) -> dict[str, Any]:
    root = Path(root)
    exports_dir = root / "data" / "exports"
    review_dir = root / "data" / "review_queue"

    runner_plan = _read_json(exports_dir / "backfill_runner_plan_r4_7.json")
    runner_manifest_rows = _read_csv(exports_dir / "backfill_runner_manifest_r4_7.csv")
    existing_slots = _read_csv(exports_dir / "import_slots_r4_7.csv")
    r46_plan_rows = _read_csv(exports_dir / "backfill_execution_plan_r4_6.csv")
    r46_status = _read_json(exports_dir / "backfill_execution_plan_r4_6_status.json")
    rebuild_status = _read_json(exports_dir / "rebuild_status.json")

    row_fabrication_policy = str(
        rebuild_status.get("row_fabrication_policy")
        or r46_status.get("row_fabrication_policy")
        or "FORBIDDEN_NO_SYNTHETIC_ROWS"
    )

    execution_rows: list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = []
    secrets_rows: list[dict[str, Any]] = []
    manifest_seed_rows: list[dict[str, Any]] = []

    forbidden_artifact_usage = False
    downloads_executed = False
    rows_ingested = 0
    production_inputs_staged = 0

    r46_lookup = {str(row.get("expected_input", "")).strip(): row for row in r46_plan_rows}

    for row in sorted(runner_manifest_rows, key=lambda r: _safe_int(r.get("priority"))):
        priority = _safe_int(row.get("priority"))
        expected_input = str(row.get("expected_input", "")).strip()
        source_family = str(row.get("source_family", "")).strip()
        target_output_path = str(row.get("target_output_path") or expected_input).strip()
        producer_script = str(row.get("likely_producer_script", "")).strip()
        expected_schema = str(row.get("expected_schema", "")).strip()
        command = str(row.get("real_run_command_template") or row.get("automated_command") or "").strip()
        dry_run_command = str(row.get("dry_run_command", "")).strip()

        classification, missing_env_vars, blocker_reason, has_forbidden, has_schema, has_automated_path, _ = _classify_source_task(
            row,
            execute_downloads=execute_downloads,
        )

        if has_forbidden:
            forbidden_artifact_usage = True

        command_selected = dry_run_command if (dry_run or not execute_downloads) else command
        command_executed = False
        command_exit_code = ""
        command_output_excerpt = ""

        if execute_downloads and classification == "executable_with_credentials":
            command_executed = True
            downloads_executed = True
            exit_code, output_excerpt = _run_command(root, command)
            command_exit_code = str(exit_code)
            command_output_excerpt = output_excerpt
            if exit_code == 0:
                # Row ingestion/staging counters are explicitly tied to executed download mode.
                rows_ingested += 0
                production_inputs_staged += 0
            else:
                blockers.append(
                    {
                        "priority": priority,
                        "expected_input": expected_input,
                        "source_family": source_family,
                        "classification": classification,
                        "blocker_reason": "command_failed",
                        "details": output_excerpt[:500],
                    }
                )
        elif classification == "missing_credentials":
            secrets_rows.append(
                {
                    "priority": priority,
                    "expected_input": expected_input,
                    "source_family": source_family,
                    "producer_script": producer_script,
                    "required_env_vars": "|".join(_split_pipe(row.get("required_env_vars", ""))),
                    "missing_env_vars": "|".join(missing_env_vars),
                    "planned_command": command,
                    "reason": blocker_reason,
                }
            )

        if classification in {"missing_schema", "manual_import_required", "blocked", "missing_credentials"}:
            blockers.append(
                {
                    "priority": priority,
                    "expected_input": expected_input,
                    "source_family": source_family,
                    "classification": classification,
                    "blocker_reason": blocker_reason,
                    "details": "|".join(missing_env_vars),
                }
            )

        planned_action = {
            "dry_run_ready": "emit_dry_run_plan",
            "executable_with_credentials": "execute_automated_download",
            "missing_credentials": "emit_credential_blocker",
            "manual_import_required": "route_to_manual_import_slot",
            "missing_schema": "route_to_schema_blocker",
            "blocked": "blocked",
        }[classification]

        r46_row = r46_lookup.get(expected_input, {})
        expected_acceptance_gate = str(r46_row.get("acceptance_gate", ""))

        execution_rows.append(
            {
                "priority": priority,
                "expected_input": expected_input,
                "source_family": source_family,
                "target_output_path": target_output_path,
                "classification": classification,
                "planned_action": planned_action,
                "dry_run_mode": bool(dry_run or not execute_downloads),
                "execute_downloads_requested": bool(execute_downloads),
                "command_selected": command_selected,
                "command_executed": command_executed,
                "command_exit_code": command_exit_code,
                "command_output_excerpt": command_output_excerpt,
                "required_env_vars": str(row.get("required_env_vars", "")),
                "missing_env_vars": "|".join(missing_env_vars),
                "expected_schema": expected_schema,
                "expected_acceptance_gate": expected_acceptance_gate,
                "blocker_reason": blocker_reason,
                "forbidden_artifact_usage": has_forbidden,
            }
        )

        manifest_seed_rows.append(
            {
                "source_system": source_family,
                "source_file": expected_input,
                "producer_script": producer_script,
                "target_output_path": target_output_path,
                "schema_version": _schema_version_for(row),
                "validation_status": classification,
                "known_gaps": blocker_reason,
            }
        )

    manual_slots = build_manual_import_slots(execution_rows, existing_slots)
    manual_validation_rows, manual_validation_errors = validate_manual_import_slots(root, manual_slots)

    write_manual_import_csv(exports_dir / "manual_import_validation_r4_8.csv", manual_validation_rows)
    write_manual_import_csv(review_dir / "manual_import_validation_errors.csv", manual_validation_errors)

    manifest_output_rel, source_manifest_count = write_source_manifest_inventory(
        root,
        manifest_seed_rows,
        output_relpath="data/exports/source_manifest_inventory_r4_8.csv",
    )

    _write_csv(
        exports_dir / "controlled_backfill_manifest_r4_8.csv",
        execution_rows,
        [
            "priority",
            "expected_input",
            "source_family",
            "target_output_path",
            "classification",
            "planned_action",
            "dry_run_mode",
            "execute_downloads_requested",
            "command_selected",
            "command_executed",
            "command_exit_code",
            "command_output_excerpt",
            "required_env_vars",
            "missing_env_vars",
            "expected_schema",
            "expected_acceptance_gate",
            "blocker_reason",
            "forbidden_artifact_usage",
        ],
    )

    _write_csv(
        review_dir / "controlled_backfill_blockers.csv",
        blockers,
        [
            "priority",
            "expected_input",
            "source_family",
            "classification",
            "blocker_reason",
            "details",
        ],
    )

    _write_csv(
        review_dir / "secrets_required_for_backfill.csv",
        secrets_rows,
        [
            "priority",
            "expected_input",
            "source_family",
            "producer_script",
            "required_env_vars",
            "missing_env_vars",
            "planned_command",
            "reason",
        ],
    )

    total_sources = len(execution_rows)
    classified_sources = sum(1 for row in execution_rows if str(row.get("classification", "")).strip())

    classification_counts = {
        "dry_run_ready": sum(1 for row in execution_rows if row.get("classification") == "dry_run_ready"),
        "executable_with_credentials": sum(1 for row in execution_rows if row.get("classification") == "executable_with_credentials"),
        "missing_credentials": sum(1 for row in execution_rows if row.get("classification") == "missing_credentials"),
        "manual_import_required": sum(1 for row in execution_rows if row.get("classification") == "manual_import_required"),
        "missing_schema": sum(1 for row in execution_rows if row.get("classification") == "missing_schema"),
        "blocked": sum(1 for row in execution_rows if row.get("classification") == "blocked"),
    }

    # Each source must map to one of the sanctioned path/blocker types.
    coverage_ok = True
    for row in execution_rows:
        classification = str(row.get("classification", ""))
        has_command = bool(str(row.get("command_selected", "")).strip())
        if classification in {"dry_run_ready", "executable_with_credentials", "missing_credentials"}:
            if not has_command:
                coverage_ok = False
                break
        elif classification == "manual_import_required":
            if not any(slot.get("expected_input") == row.get("expected_input") for slot in manual_slots):
                coverage_ok = False
                break
        elif classification == "missing_schema":
            continue
        else:
            coverage_ok = False
            break

    phase_7_8_blocked = True

    r4_8_gate_passed = bool(
        total_sources == len(runner_manifest_rows)
        and classified_sources == total_sources
        and coverage_ok
        and not forbidden_artifact_usage
        and row_fabrication_policy == "FORBIDDEN_NO_SYNTHETIC_ROWS"
        and phase_7_8_blocked
    )

    plan_payload = {
        "generated_at": _utc_now(),
        "r4_8_phase_type": "CONTROLLED_BACKFILL_EXECUTION_AND_MANUAL_IMPORT_VALIDATION",
        "dry_run": bool(dry_run or not execute_downloads),
        "execute_downloads_requested": bool(execute_downloads),
        "r4_8_execute_downloads_default": False,
        "r4_8_gate_passed": r4_8_gate_passed,
        "r4_8_total_sources": total_sources,
        "r4_8_dry_run_ready_count": classification_counts["dry_run_ready"],
        "r4_8_executable_with_credentials_count": classification_counts["executable_with_credentials"],
        "r4_8_missing_credentials_count": classification_counts["missing_credentials"],
        "r4_8_manual_import_required_count": classification_counts["manual_import_required"],
        "r4_8_missing_schema_count": classification_counts["missing_schema"],
        "r4_8_blocked_count": classification_counts["blocked"],
        "r4_8_downloads_executed": downloads_executed,
        "r4_8_rows_ingested": rows_ingested,
        "r4_8_production_inputs_staged": production_inputs_staged,
        "r4_8_source_manifests_written": source_manifest_count,
        "r4_8_data_recovery_completed": bool(
            execute_downloads and downloads_executed and rows_ingested > 0 and production_inputs_staged > 0
        ),
        "row_fabrication_policy": row_fabrication_policy,
        "forbidden_artifact_usage": forbidden_artifact_usage,
        "phase_7_8_blocked": phase_7_8_blocked,
        "phase_7_8_block_reason": "R4.8 preserves Phase 7/8 block until R5/R6/R7 gates pass.",
        "secrets_required_count": len(secrets_rows),
        "manual_slot_count": len(manual_slots),
        "manual_import_validation_error_count": len(manual_validation_errors),
        "inputs": {
            "backfill_runner_plan": "data/exports/backfill_runner_plan_r4_7.json",
            "backfill_runner_manifest": "data/exports/backfill_runner_manifest_r4_7.csv",
            "import_slots": "data/exports/import_slots_r4_7.csv",
            "backfill_execution_plan": "data/exports/backfill_execution_plan_r4_6.csv",
            "backfill_execution_status": "data/exports/backfill_execution_plan_r4_6_status.json",
        },
        "outputs": {
            "controlled_backfill_plan": "data/exports/controlled_backfill_plan_r4_8.json",
            "controlled_backfill_manifest": "data/exports/controlled_backfill_manifest_r4_8.csv",
            "manual_import_validation": "data/exports/manual_import_validation_r4_8.csv",
            "source_manifest_inventory": manifest_output_rel,
            "controlled_backfill_blockers": "data/review_queue/controlled_backfill_blockers.csv",
            "manual_import_validation_errors": "data/review_queue/manual_import_validation_errors.csv",
            "secrets_required_for_backfill": "data/review_queue/secrets_required_for_backfill.csv",
        },
    }

    _write_json(exports_dir / "controlled_backfill_plan_r4_8.json", plan_payload)

    # Update rebuild status with required R4.8 fields.
    next_rebuild_status = dict(rebuild_status)
    next_rebuild_status.update(
        {
            "r4_8_generated_at": plan_payload["generated_at"],
            "r4_8_phase_type": plan_payload["r4_8_phase_type"],
            "r4_8_gate_passed": plan_payload["r4_8_gate_passed"],
            "r4_8_total_sources": plan_payload["r4_8_total_sources"],
            "r4_8_dry_run_ready_count": plan_payload["r4_8_dry_run_ready_count"],
            "r4_8_executable_with_credentials_count": plan_payload["r4_8_executable_with_credentials_count"],
            "r4_8_missing_credentials_count": plan_payload["r4_8_missing_credentials_count"],
            "r4_8_manual_import_required_count": plan_payload["r4_8_manual_import_required_count"],
            "r4_8_missing_schema_count": plan_payload["r4_8_missing_schema_count"],
            "r4_8_blocked_count": plan_payload["r4_8_blocked_count"],
            "r4_8_downloads_executed": plan_payload["r4_8_downloads_executed"],
            "r4_8_rows_ingested": plan_payload["r4_8_rows_ingested"],
            "r4_8_production_inputs_staged": plan_payload["r4_8_production_inputs_staged"],
            "r4_8_source_manifests_written": plan_payload["r4_8_source_manifests_written"],
            "r4_8_data_recovery_completed": plan_payload["r4_8_data_recovery_completed"],
            "row_fabrication_policy": row_fabrication_policy,
            "phase_7_8_blocked": True,
            "phase_7_8_block_reason": plan_payload["phase_7_8_block_reason"],
            "r4_8_outputs": plan_payload["outputs"],
        }
    )
    _write_json(exports_dir / "rebuild_status.json", next_rebuild_status)

    return plan_payload
