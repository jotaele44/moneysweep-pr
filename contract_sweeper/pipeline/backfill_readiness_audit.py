"""R4.8A controlled backfill execution readiness audit.

This phase audits whether planned R4.8 source tasks are ready for real execution or
manual import. It does not execute downloads or ingest data.
"""

from __future__ import annotations

import csv
import json
import os
import re
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

READINESS_CLASSES = {
    "ready_for_execute_downloads",
    "requires_credentials",
    "requires_manual_file",
    "requires_schema_mapping",
    "requires_producer_script",
    "blocked_forbidden_artifact",
    "blocked_unknown",
}


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


def _slug(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() else "_" for ch in value.lower())
    while "__" in cleaned:
        cleaned = cleaned.replace("__", "_")
    return cleaned.strip("_") or "source"


def _default_dropzone(source_family: str, expected_input: str) -> str:
    return f"data/manual_import_dropzone/{_slug(source_family)}/{Path(expected_input).name}"


def _default_patterns(target_output_path: str) -> str:
    suffix = Path(target_output_path).suffix.lower()
    if suffix == ".csv":
        return "*.csv"
    if suffix == ".parquet":
        return "*.parquet"
    return "*.csv|*.xlsx|*.xls|*.parquet"


def _scan_script_env_vars(path: Path) -> list[str]:
    if not path.exists() or not path.is_file():
        return []

    text = path.read_text(encoding="utf-8", errors="replace")
    hits = set(re.findall(r"(?:os\.)?getenv\([\"']([A-Z0-9_]+)[\"']", text))
    hits.update(re.findall(r"os\.environ\[[\"']([A-Z0-9_]+)[\"']\]", text))
    return sorted(hits)


def _schema_known(row: dict[str, Any], schema_registry_text: str) -> bool:
    explicit_schema = str(row.get("expected_schema", "")).strip()
    if explicit_schema:
        return True

    expected_input = str(row.get("expected_input", "")).strip()
    target_output = str(row.get("target_output_path", "")).strip()
    needle_1 = Path(expected_input).name
    needle_2 = Path(target_output).name
    if schema_registry_text and (needle_1 in schema_registry_text or needle_2 in schema_registry_text):
        return True

    return False


def _next_action_for(readiness: str) -> str:
    mapping = {
        "ready_for_execute_downloads": "ready: execute with --execute-downloads in next controlled phase",
        "requires_credentials": "set required env vars in .env and rerun readiness audit",
        "requires_manual_file": "place required file in dropzone and rerun readiness audit",
        "requires_schema_mapping": "register/confirm schema mapping in registry before execution",
        "requires_producer_script": "add or repair producer script path before execution",
        "blocked_forbidden_artifact": "replace forbidden artifact path with allowed source/staging input",
        "blocked_unknown": "investigate source task wiring and define explicit execution path",
    }
    return mapping.get(readiness, "investigate unknown readiness state")


def run_backfill_readiness_audit(root: Path) -> dict[str, Any]:
    root = Path(root)
    exports_dir = root / "data" / "exports"
    review_dir = root / "data" / "review_queue"

    controlled_plan = _read_json(exports_dir / "controlled_backfill_plan_r4_8.json")
    controlled_manifest = _read_csv(exports_dir / "controlled_backfill_manifest_r4_8.csv")
    source_manifest_inventory = _read_csv(exports_dir / "source_manifest_inventory_r4_8.csv")
    runner_manifest = _read_csv(exports_dir / "backfill_runner_manifest_r4_7.csv")
    backfill_plan_r46 = _read_csv(exports_dir / "backfill_execution_plan_r4_6.csv")
    rebuild_status = _read_json(exports_dir / "rebuild_status.json")

    source_registry_text = ""
    source_registry_path = root / "configs" / "source_registry.yaml"
    if source_registry_path.exists():
        source_registry_text = source_registry_path.read_text(encoding="utf-8", errors="replace")

    schema_registry_text = ""
    schema_registry_path = root / "configs" / "schema_registry.yaml"
    if schema_registry_path.exists():
        schema_registry_text = schema_registry_path.read_text(encoding="utf-8", errors="replace")

    row_fabrication_policy = str(
        rebuild_status.get("row_fabrication_policy")
        or controlled_plan.get("row_fabrication_policy")
        or "FORBIDDEN_NO_SYNTHETIC_ROWS"
    )

    runner_by_expected = {
        str(row.get("expected_input", "")).strip(): row
        for row in runner_manifest
        if str(row.get("expected_input", "")).strip()
    }
    plan_by_expected = {
        str(row.get("expected_input", "")).strip(): row
        for row in backfill_plan_r46
        if str(row.get("expected_input", "")).strip()
    }
    inv_by_source = {
        str(row.get("source_file", "")).strip(): row
        for row in source_manifest_inventory
        if str(row.get("source_file", "")).strip()
    }

    readiness_rows: list[dict[str, Any]] = []
    blockers_rows: list[dict[str, Any]] = []
    credentials_rows: list[dict[str, Any]] = []
    manual_files_rows: list[dict[str, Any]] = []
    schema_rows: list[dict[str, Any]] = []

    forbidden_artifact_usage = False

    for row in sorted(controlled_manifest, key=lambda r: _safe_int(r.get("priority"))):
        priority = _safe_int(row.get("priority"))
        expected_input = str(row.get("expected_input", "")).strip()
        source_family = str(row.get("source_family", "")).strip()
        target_output_path = str(row.get("target_output_path") or expected_input).strip()

        runner_row = runner_by_expected.get(expected_input, {})
        producer_script = str(runner_row.get("likely_producer_script", "")).strip()
        producer_script_exists = bool(producer_script and (root / producer_script).exists())

        required_env_vars = sorted(
            set(
                _split_pipe(runner_row.get("required_env_vars", ""))
                + _scan_script_env_vars(root / producer_script) if producer_script else _split_pipe(runner_row.get("required_env_vars", ""))
            )
        )
        missing_env_vars = [env for env in required_env_vars if not os.getenv(env)]
        credentials_present = bool(not missing_env_vars)

        expected_schema_known = _schema_known(
            {
                "expected_schema": runner_row.get("expected_schema") or row.get("expected_schema", ""),
                "expected_input": expected_input,
                "target_output_path": target_output_path,
            },
            schema_registry_text,
        )

        validation_command = str(runner_row.get("validation_command", "")).strip()
        has_validation_command = bool(validation_command)

        command = str(runner_row.get("real_run_command_template") or runner_row.get("automated_command") or "").strip()
        has_automated_command = bool(command)

        manual_path_required = (
            str(runner_row.get("classification", "")).strip() == "manual_import_required"
            or str(runner_row.get("requires_manual_export", "")).strip().lower() == "true"
            or (not has_automated_command)
        )

        dropzone_path = str(runner_row.get("dropzone_path", "")).strip()
        if not dropzone_path and manual_path_required:
            dropzone_path = _default_dropzone(source_family or "source", expected_input)

        accepted_file_patterns = str(runner_row.get("accepted_file_patterns", "")).strip()
        if not accepted_file_patterns and manual_path_required:
            accepted_file_patterns = _default_patterns(target_output_path)

        required_columns = str(runner_row.get("expected_schema") or row.get("expected_schema", "")).strip()
        manifest_path = f"{target_output_path}.manifest.json"

        planning_manifest_present = expected_input in inv_by_source
        validated_manifest_present = (root / manifest_path).exists()

        has_forbidden = any(
            _contains_forbidden_token(candidate)
            for candidate in [expected_input, target_output_path, dropzone_path, manifest_path]
            if candidate
        )
        forbidden_artifact_usage = bool(forbidden_artifact_usage or has_forbidden)

        if has_forbidden:
            readiness = "blocked_forbidden_artifact"
            reason = "forbidden artifact token detected"
        elif not expected_schema_known:
            readiness = "requires_schema_mapping"
            reason = "expected schema not known"
        elif manual_path_required and not (dropzone_path and (root / dropzone_path).exists()):
            readiness = "requires_manual_file"
            reason = "manual source file missing from dropzone"
        elif not producer_script or not producer_script_exists:
            readiness = "requires_producer_script"
            reason = "producer script missing"
        elif required_env_vars and not credentials_present:
            readiness = "requires_credentials"
            reason = "required credentials not present"
        elif has_automated_command:
            readiness = "ready_for_execute_downloads"
            reason = "ready for controlled execution"
        else:
            readiness = "blocked_unknown"
            reason = "no executable path identified"

        next_action = _next_action_for(readiness)

        if readiness in {
            "requires_credentials",
            "requires_manual_file",
            "requires_schema_mapping",
            "requires_producer_script",
            "blocked_forbidden_artifact",
            "blocked_unknown",
        }:
            blockers_rows.append(
                {
                    "priority": priority,
                    "expected_input": expected_input,
                    "source_family": source_family,
                    "readiness": readiness,
                    "reason": reason,
                    "next_action": next_action,
                }
            )

        if readiness == "requires_credentials":
            credentials_rows.append(
                {
                    "priority": priority,
                    "expected_input": expected_input,
                    "source_family": source_family,
                    "producer_script": producer_script,
                    "required_env_vars": "|".join(required_env_vars),
                    "missing_env_vars": "|".join(missing_env_vars),
                    "next_action": next_action,
                }
            )

        if readiness == "requires_manual_file":
            manual_files_rows.append(
                {
                    "priority": priority,
                    "expected_input": expected_input,
                    "source_family": source_family,
                    "dropzone_path": dropzone_path,
                    "accepted_file_patterns": accepted_file_patterns,
                    "required_columns": required_columns,
                    "target_output_path": target_output_path,
                    "manifest_path": manifest_path,
                    "next_action": next_action,
                }
            )

        if readiness == "requires_schema_mapping":
            schema_rows.append(
                {
                    "priority": priority,
                    "expected_input": expected_input,
                    "source_family": source_family,
                    "target_output_path": target_output_path,
                    "schema_registry_checked": str(schema_registry_path.exists()),
                    "next_action": next_action,
                }
            )

        readiness_rows.append(
            {
                "priority": priority,
                "expected_input": expected_input,
                "source_family": source_family,
                "readiness": readiness,
                "next_action": next_action,
                "reason": reason,
                "producer_script": producer_script,
                "producer_script_exists": producer_script_exists,
                "required_env_vars": "|".join(required_env_vars),
                "credentials_present": credentials_present,
                "missing_env_vars": "|".join(missing_env_vars),
                "target_output_path": target_output_path,
                "expected_schema_known": expected_schema_known,
                "validation_command": validation_command,
                "has_validation_command": has_validation_command,
                "manifest_path": manifest_path,
                "planning_manifest_present": planning_manifest_present,
                "validated_manifest_present": validated_manifest_present,
                "manual_path_required": manual_path_required,
                "dropzone_path": dropzone_path,
                "accepted_file_patterns": accepted_file_patterns,
                "forbidden_artifact_usage": has_forbidden,
                "row_fabrication_policy": row_fabrication_policy,
            }
        )

    total_sources = len(readiness_rows)
    all_classified = all(row.get("readiness") in READINESS_CLASSES for row in readiness_rows)
    all_have_next_action = all(bool(str(row.get("next_action", "")).strip()) for row in readiness_rows)

    counts = {
        "ready_for_execute_downloads": sum(1 for row in readiness_rows if row.get("readiness") == "ready_for_execute_downloads"),
        "requires_credentials": sum(1 for row in readiness_rows if row.get("readiness") == "requires_credentials"),
        "requires_manual_file": sum(1 for row in readiness_rows if row.get("readiness") == "requires_manual_file"),
        "requires_schema_mapping": sum(1 for row in readiness_rows if row.get("readiness") == "requires_schema_mapping"),
        "requires_producer_script": sum(1 for row in readiness_rows if row.get("readiness") == "requires_producer_script"),
        "blocked_forbidden_artifact": sum(1 for row in readiness_rows if row.get("readiness") == "blocked_forbidden_artifact"),
        "blocked_unknown": sum(1 for row in readiness_rows if row.get("readiness") == "blocked_unknown"),
    }

    downloads_executed = False
    rows_ingested = 0
    production_inputs_staged = 0
    validated_source_manifests_written = 0

    phase_7_8_blocked = True

    # Ensure explicit queueing for relevant blocker classes.
    queue_coverage_ok = (
        len(credentials_rows) == counts["requires_credentials"]
        and len(manual_files_rows) == counts["requires_manual_file"]
        and len(schema_rows) == counts["requires_schema_mapping"]
        and len(
            [
                row
                for row in readiness_rows
                if row.get("readiness") in {
                    "requires_credentials",
                    "requires_manual_file",
                    "requires_schema_mapping",
                    "requires_producer_script",
                    "blocked_forbidden_artifact",
                    "blocked_unknown",
                }
            ]
        )
        == len(blockers_rows)
    )

    # planning manifest inventory written in R4.8; these are not validated source manifests.
    planning_manifest_count = len(source_manifest_inventory)

    r4_8a_gate_passed = bool(
        total_sources == len(controlled_manifest)
        and all_classified
        and all_have_next_action
        and queue_coverage_ok
        and not downloads_executed
        and rows_ingested == 0
        and production_inputs_staged == 0
        and not forbidden_artifact_usage
        and phase_7_8_blocked
        and row_fabrication_policy == "FORBIDDEN_NO_SYNTHETIC_ROWS"
    )

    _write_csv(
        exports_dir / "backfill_readiness_matrix_r4_8a.csv",
        readiness_rows,
        [
            "priority",
            "expected_input",
            "source_family",
            "readiness",
            "next_action",
            "reason",
            "producer_script",
            "producer_script_exists",
            "required_env_vars",
            "credentials_present",
            "missing_env_vars",
            "target_output_path",
            "expected_schema_known",
            "validation_command",
            "has_validation_command",
            "manifest_path",
            "planning_manifest_present",
            "validated_manifest_present",
            "manual_path_required",
            "dropzone_path",
            "accepted_file_patterns",
            "forbidden_artifact_usage",
            "row_fabrication_policy",
        ],
    )

    _write_csv(
        review_dir / "backfill_execution_blockers_r4_8a.csv",
        blockers_rows,
        ["priority", "expected_input", "source_family", "readiness", "reason", "next_action"],
    )

    _write_csv(
        review_dir / "credentials_required_r4_8a.csv",
        credentials_rows,
        [
            "priority",
            "expected_input",
            "source_family",
            "producer_script",
            "required_env_vars",
            "missing_env_vars",
            "next_action",
        ],
    )

    _write_csv(
        review_dir / "manual_files_required_r4_8a.csv",
        manual_files_rows,
        [
            "priority",
            "expected_input",
            "source_family",
            "dropzone_path",
            "accepted_file_patterns",
            "required_columns",
            "target_output_path",
            "manifest_path",
            "next_action",
        ],
    )

    _write_csv(
        review_dir / "schema_required_r4_8a.csv",
        schema_rows,
        [
            "priority",
            "expected_input",
            "source_family",
            "target_output_path",
            "schema_registry_checked",
            "next_action",
        ],
    )

    status = {
        "generated_at": _utc_now(),
        "r4_8a_phase_type": "CONTROLLED_BACKFILL_EXECUTION_READINESS_AUDIT",
        "r4_8a_gate_passed": r4_8a_gate_passed,
        "r4_8a_total_sources": total_sources,
        "r4_8a_ready_for_execute_downloads_count": counts["ready_for_execute_downloads"],
        "r4_8a_requires_credentials_count": counts["requires_credentials"],
        "r4_8a_requires_manual_file_count": counts["requires_manual_file"],
        "r4_8a_requires_schema_mapping_count": counts["requires_schema_mapping"],
        "r4_8a_requires_producer_script_count": counts["requires_producer_script"],
        "r4_8a_blocked_count": counts["blocked_forbidden_artifact"] + counts["blocked_unknown"],
        "r4_8a_downloads_executed": downloads_executed,
        "r4_8a_rows_ingested": rows_ingested,
        "r4_8a_production_inputs_staged": production_inputs_staged,
        "r4_8a_validated_source_manifests_written": validated_source_manifests_written,
        "r4_8a_planning_manifest_count": planning_manifest_count,
        "phase_7_8_blocked": phase_7_8_blocked,
        "row_fabrication_policy": row_fabrication_policy,
        "forbidden_artifact_usage": forbidden_artifact_usage,
        "inputs": {
            "controlled_backfill_plan": "data/exports/controlled_backfill_plan_r4_8.json",
            "controlled_backfill_manifest": "data/exports/controlled_backfill_manifest_r4_8.csv",
            "source_manifest_inventory": "data/exports/source_manifest_inventory_r4_8.csv",
            "backfill_runner_manifest": "data/exports/backfill_runner_manifest_r4_7.csv",
            "backfill_execution_plan": "data/exports/backfill_execution_plan_r4_6.csv",
        },
        "outputs": {
            "backfill_readiness_matrix": "data/exports/backfill_readiness_matrix_r4_8a.csv",
            "backfill_readiness_status": "data/exports/backfill_readiness_status_r4_8a.json",
            "backfill_execution_blockers": "data/review_queue/backfill_execution_blockers_r4_8a.csv",
            "credentials_required": "data/review_queue/credentials_required_r4_8a.csv",
            "manual_files_required": "data/review_queue/manual_files_required_r4_8a.csv",
            "schema_required": "data/review_queue/schema_required_r4_8a.csv",
        },
    }

    _write_json(exports_dir / "backfill_readiness_status_r4_8a.json", status)

    next_rebuild_status = dict(rebuild_status)
    next_rebuild_status.update(
        {
            "r4_8a_generated_at": status["generated_at"],
            "r4_8a_gate_passed": status["r4_8a_gate_passed"],
            "r4_8a_total_sources": status["r4_8a_total_sources"],
            "r4_8a_ready_for_execute_downloads_count": status["r4_8a_ready_for_execute_downloads_count"],
            "r4_8a_requires_credentials_count": status["r4_8a_requires_credentials_count"],
            "r4_8a_requires_manual_file_count": status["r4_8a_requires_manual_file_count"],
            "r4_8a_requires_schema_mapping_count": status["r4_8a_requires_schema_mapping_count"],
            "r4_8a_requires_producer_script_count": status["r4_8a_requires_producer_script_count"],
            "r4_8a_blocked_count": status["r4_8a_blocked_count"],
            "r4_8a_downloads_executed": status["r4_8a_downloads_executed"],
            "r4_8a_rows_ingested": status["r4_8a_rows_ingested"],
            "r4_8a_production_inputs_staged": status["r4_8a_production_inputs_staged"],
            "r4_8a_validated_source_manifests_written": status["r4_8a_validated_source_manifests_written"],
            "r4_8a_planning_manifest_count": status["r4_8a_planning_manifest_count"],
            "phase_7_8_blocked": True,
            "phase_7_8_block_reason": "R4.8A readiness audit keeps Phase 7/8 blocked until downstream gates pass.",
            "row_fabrication_policy": row_fabrication_policy,
            "r4_8a_outputs": status["outputs"],
        }
    )
    _write_json(exports_dir / "rebuild_status.json", next_rebuild_status)

    return status
