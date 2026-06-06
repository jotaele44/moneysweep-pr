"""R4.8C source blocker remediation and manual fallback planning."""

from __future__ import annotations

import csv
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from contract_sweeper.pipeline.schema_remediation import (
    build_recommended_mapping,
    infer_candidate_column_aliases,
    read_observed_columns,
    serialize_json,
    split_pipe,
)

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

PRIMARY_BLOCKER_CLASSES = {
    "producer_timeout",
    "producer_exception",
    "missing_manual_source",
    "schema_mismatch",
    "no_data",
    "credential_missing",
    "endpoint_unavailable",
    "forbidden_artifact_rejected",
    "unknown_failure",
}

NEXT_ACTIONS = {
    "patch_producer_script",
    "add_schema_mapping",
    "require_manual_file",
    "increase_timeout_with_cap",
    "endpoint_review",
    "retry_after_fix",
    "leave_blocked_with_reason",
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


def _safe_int(raw: Any) -> int:
    try:
        return int(float(str(raw).strip()))
    except (TypeError, ValueError):
        return 0


def _to_bool(raw: Any) -> bool:
    return str(raw).strip().lower() in {"1", "true", "yes", "y"}


def _contains_forbidden_token(text: str) -> bool:
    lowered = str(text).lower()
    return any(token in lowered for token in FORBIDDEN_ARTIFACT_TOKENS)


def _default_patterns(output_path: str) -> str:
    suffix = Path(output_path).suffix.lower()
    if suffix == ".csv":
        return "*.csv"
    if suffix == ".parquet":
        return "*.parquet"
    if suffix == ".xlsx":
        return "*.xlsx"
    return "*.csv|*.parquet|*.xlsx|*.xls"


def _default_dropzone(source_family: str, expected_input: str) -> str:
    slug = "".join(ch if ch.isalnum() else "_" for ch in source_family.lower()).strip("_") or "source"
    return f"data/manual_import_dropzone/{slug}/{Path(expected_input).name}"


def _required_file_type(path: str) -> str:
    suffix = Path(path).suffix.lower().lstrip(".")
    return suffix or "csv"


def _stderr_excerpt_safe(reason: str, max_len: int = 240) -> str:
    text = str(reason or "").replace("\n", " ").replace("\r", " ").strip()
    text = re.sub(r"\s+", " ", text)
    return text[:max_len]


def _extract_timeout_seconds(reason: str) -> str:
    match = re.search(r"after\s+(\d+)s", str(reason or ""))
    if match:
        return match.group(1)
    return ""


def _classify_failure(
    *,
    terminal_status: str,
    reason: str,
    expected_input: str,
    producer_script: str,
    source_url_or_portal: str,
    missing_env_vars: str,
    manual_path_required: bool,
    forbidden_artifact_usage: bool,
) -> tuple[str, str]:
    status = str(terminal_status or "").strip()
    lower_reason = str(reason or "").lower()

    if forbidden_artifact_usage or _contains_forbidden_token(expected_input):
        return "forbidden_artifact_rejected", "leave_blocked_with_reason"

    if status == "credential_failure" or str(missing_env_vars).strip():
        return "credential_missing", "leave_blocked_with_reason"

    if status == "schema_failure":
        return "schema_mismatch", "add_schema_mapping"

    if status == "no_data":
        if manual_path_required:
            return "missing_manual_source", "require_manual_file"
        return "no_data", "retry_after_fix"

    if status == "execution_timeout":
        if producer_script.startswith("scripts/download_") or producer_script == "scripts/auto_download.py" or source_url_or_portal:
            return "endpoint_unavailable", "endpoint_review"
        return "producer_timeout", "increase_timeout_with_cap"

    if status == "execution_failed":
        endpoint_tokens = (
            "http",
            "timeout",
            "connection",
            "dns",
            "ssl",
            "429",
            "5xx",
            "service unavailable",
            "endpoint",
        )
        if any(token in lower_reason for token in endpoint_tokens):
            return "endpoint_unavailable", "endpoint_review"
        return "producer_exception", "patch_producer_script"

    if status in {"skipped_not_ready", "manual_fallback_required"}:
        return "missing_manual_source", "require_manual_file"

    return "unknown_failure", "leave_blocked_with_reason"


def _producer_patch_hint(blocker_class: str, producer_script: str) -> str:
    if blocker_class == "producer_timeout":
        return "Increase timeout cap (for example 20s -> 120s), keep retry/backoff, and add checkpoint logging."
    if blocker_class == "endpoint_unavailable":
        return "Review endpoint availability/rate limits; add bounded retry budget and explicit endpoint health diagnostics."
    if blocker_class == "producer_exception":
        return "Patch script exception path, validate output path creation, and return explicit failure diagnostics."
    if blocker_class == "no_data":
        return "Verify upstream dependencies and fail-closed when prerequisite source files are missing."
    return "Investigate producer behavior and add explicit guardrails before retry."


def run_backfill_failure_remediation(
    root: Path,
    *,
    retry_attempted: bool = False,
    retry_scope: str = "",
) -> dict[str, Any]:
    root = Path(root)
    exports_dir = root / "data" / "exports"
    review_dir = root / "data" / "review_queue"

    results_rows = _read_csv(exports_dir / "controlled_backfill_execution_results_r4_8b.csv")
    status_r48b = _read_json(exports_dir / "controlled_backfill_execution_status_r4_8b.json")
    failure_rows = _read_csv(review_dir / "controlled_backfill_execution_failures_r4_8b.csv")
    schema_failure_rows = _read_csv(review_dir / "schema_failures_r4_8b.csv")
    manual_fallback_rows = _read_csv(review_dir / "manual_fallback_required_r4_8b.csv")
    no_data_rows = _read_csv(review_dir / "no_data_sources_r4_8b.csv")
    credential_failure_rows = _read_csv(review_dir / "credential_failures_r4_8b.csv")

    readiness_rows = _read_csv(exports_dir / "backfill_readiness_matrix_r4_8a.csv")
    r46_rows = _read_csv(exports_dir / "backfill_execution_plan_r4_6.csv")
    runner_rows = _read_csv(exports_dir / "backfill_runner_manifest_r4_7.csv")
    rebuild_status = _read_json(exports_dir / "rebuild_status.json")

    source_registry_text = ""
    source_registry_path = root / "configs" / "source_registry.yaml"
    if source_registry_path.exists():
        source_registry_text = source_registry_path.read_text(encoding="utf-8", errors="replace")

    row_fabrication_policy = str(
        rebuild_status.get("row_fabrication_policy")
        or status_r48b.get("row_fabrication_policy")
        or "FORBIDDEN_NO_SYNTHETIC_ROWS"
    )

    results_by_input = {
        str(row.get("expected_input", "")).strip(): row
        for row in results_rows
        if str(row.get("expected_input", "")).strip()
    }
    readiness_by_input = {
        str(row.get("expected_input", "")).strip(): row
        for row in readiness_rows
        if str(row.get("expected_input", "")).strip()
    }
    r46_by_input = {
        str(row.get("expected_input", "")).strip(): row
        for row in r46_rows
        if str(row.get("expected_input", "")).strip()
    }
    runner_by_input = {
        str(row.get("expected_input", "")).strip(): row
        for row in runner_rows
        if str(row.get("expected_input", "")).strip()
    }
    schema_failure_by_input = {
        str(row.get("expected_input", "")).strip(): row
        for row in schema_failure_rows
        if str(row.get("expected_input", "")).strip()
    }

    remediation_rows: list[dict[str, Any]] = []
    producer_fix_queue: list[dict[str, Any]] = []
    schema_queue: list[dict[str, Any]] = []
    manual_queue: list[dict[str, Any]] = []
    endpoint_queue: list[dict[str, Any]] = []

    forbidden_artifact_usage = False

    for failure in sorted(failure_rows, key=lambda r: _safe_int(r.get("priority"))):
        priority = _safe_int(failure.get("priority"))
        expected_input = str(failure.get("expected_input", "")).strip()
        source_family = str(failure.get("source_family", "")).strip()

        result = results_by_input.get(expected_input, {})
        readiness = readiness_by_input.get(expected_input, {})
        runner = runner_by_input.get(expected_input, {})
        r46 = r46_by_input.get(expected_input, {})

        target_output_path = str(
            result.get("target_output_path")
            or readiness.get("target_output_path")
            or r46.get("output_path")
            or expected_input
        ).strip()

        producer_script = str(
            result.get("producer_script")
            or readiness.get("producer_script")
            or runner.get("likely_producer_script")
            or r46.get("producer_script")
            or ""
        ).strip()

        source_url_or_portal = str(runner.get("source_url_or_portal", "")).strip()
        required_env_vars = str(
            result.get("required_env_vars") or readiness.get("required_env_vars") or runner.get("required_env_vars") or ""
        ).strip()
        missing_env_vars = str(
            result.get("missing_env_vars") or readiness.get("missing_env_vars") or ""
        ).strip()

        terminal_status = str(failure.get("terminal_status") or result.get("terminal_status") or "").strip()
        reason = str(failure.get("reason") or result.get("blocker_reason") or "").strip()

        manual_path_required = _to_bool(readiness.get("manual_path_required"))

        forbidden_for_source = bool(
            _to_bool(result.get("forbidden_artifact_usage"))
            or _to_bool(readiness.get("forbidden_artifact_usage"))
            or _contains_forbidden_token(expected_input)
            or _contains_forbidden_token(target_output_path)
        )
        forbidden_artifact_usage = bool(forbidden_artifact_usage or forbidden_for_source)

        blocker_class, next_action = _classify_failure(
            terminal_status=terminal_status,
            reason=reason,
            expected_input=expected_input,
            producer_script=producer_script,
            source_url_or_portal=source_url_or_portal,
            missing_env_vars=missing_env_vars,
            manual_path_required=manual_path_required,
            forbidden_artifact_usage=forbidden_for_source,
        )

        if blocker_class not in PRIMARY_BLOCKER_CLASSES:
            blocker_class = "unknown_failure"
            next_action = "leave_blocked_with_reason"

        if next_action not in NEXT_ACTIONS:
            next_action = "leave_blocked_with_reason"

        acceptance_gate = str(r46.get("acceptance_gate", "")).strip()
        recommended_action = str(r46.get("recommended_action", "")).strip()

        remediation_rows.append(
            {
                "priority": priority,
                "expected_input": expected_input,
                "source_family": source_family,
                "target_output_path": target_output_path,
                "terminal_status": terminal_status,
                "primary_blocker_class": blocker_class,
                "next_action": next_action,
                "reason": reason,
                "producer_script": producer_script,
                "source_url_or_portal": source_url_or_portal,
                "required_env_vars": required_env_vars,
                "missing_env_vars": missing_env_vars,
                "validation_command": str(
                    result.get("validation_command")
                    or readiness.get("validation_command")
                    or runner.get("validation_command")
                    or ""
                ).strip(),
                "acceptance_gate": acceptance_gate,
                "recommended_action_r46": recommended_action,
                "forbidden_artifact_usage": forbidden_for_source,
            }
        )

        if blocker_class in {"producer_timeout", "producer_exception", "endpoint_unavailable", "no_data"}:
            producer_fix_queue.append(
                {
                    "priority": priority,
                    "expected_input": expected_input,
                    "source_family": source_family,
                    "producer_script": producer_script,
                    "error_type": blocker_class,
                    "stderr_excerpt_safe": _stderr_excerpt_safe(reason),
                    "timeout_seconds": _extract_timeout_seconds(reason),
                    "recommended_patch": _producer_patch_hint(blocker_class, producer_script),
                    "next_action": next_action,
                }
            )

        if blocker_class == "schema_mismatch":
            schema_row = schema_failure_by_input.get(expected_input, {})
            required_columns = split_pipe(
                schema_row.get("expected_schema") or runner.get("expected_schema") or ""
            )
            observed_columns = read_observed_columns(root, target_output_path)

            missing_columns = split_pipe(schema_row.get("missing_columns", ""))
            if not missing_columns and required_columns:
                observed_set = {col for col in observed_columns}
                missing_columns = [col for col in required_columns if col not in observed_set]

            candidate_aliases = infer_candidate_column_aliases(required_columns, observed_columns)
            recommended_mapping = build_recommended_mapping(candidate_aliases)

            schema_queue.append(
                {
                    "priority": priority,
                    "expected_input": expected_input,
                    "source_family": source_family,
                    "observed_columns": "|".join(observed_columns),
                    "required_columns": "|".join(required_columns),
                    "missing_columns": "|".join(missing_columns),
                    "candidate_column_aliases": serialize_json(candidate_aliases),
                    "recommended_mapping": serialize_json(recommended_mapping),
                    "next_action": next_action,
                }
            )

        if blocker_class == "endpoint_unavailable":
            endpoint_queue.append(
                {
                    "priority": priority,
                    "expected_input": expected_input,
                    "source_family": source_family,
                    "source_url_or_portal": source_url_or_portal,
                    "producer_script": producer_script,
                    "reason": reason,
                    "recommended_review": "Check endpoint status/rate limits; retry with bounded timeout and backoff.",
                    "next_action": next_action,
                }
            )

    # Manual fallback queue uses explicit R4.8B fallback list.
    for row in sorted(manual_fallback_rows, key=lambda r: _safe_int(r.get("priority"))):
        priority = _safe_int(row.get("priority"))
        expected_input = str(row.get("expected_input", "")).strip()
        source_family = str(row.get("source_family", "")).strip()
        readiness = readiness_by_input.get(expected_input, {})
        result = results_by_input.get(expected_input, {})
        runner = runner_by_input.get(expected_input, {})
        r46 = r46_by_input.get(expected_input, {})

        target_output_path = str(
            result.get("target_output_path")
            or readiness.get("target_output_path")
            or r46.get("output_path")
            or expected_input
        ).strip()

        required_columns = str(runner.get("expected_schema") or "").strip()
        dropzone_path = str(readiness.get("dropzone_path") or "").strip()
        if not dropzone_path:
            dropzone_path = _default_dropzone(source_family or "source", expected_input)

        accepted_patterns = str(readiness.get("accepted_file_patterns") or "").strip()
        if not accepted_patterns:
            accepted_patterns = _default_patterns(target_output_path)

        source_url_or_portal = str(runner.get("source_url_or_portal") or "").strip()
        if not source_url_or_portal and source_registry_text:
            if source_family and source_family in source_registry_text:
                source_url_or_portal = "registry_lookup_required"

        manual_queue.append(
            {
                "priority": priority,
                "source_family": source_family,
                "expected_input": expected_input,
                "source_url_or_portal": source_url_or_portal,
                "required_file_type": _required_file_type(target_output_path),
                "accepted_filename_patterns": accepted_patterns,
                "required_columns": required_columns,
                "target_dropzone_path": dropzone_path,
                "target_output_path": target_output_path,
                "validation_command": str(
                    result.get("validation_command")
                    or readiness.get("validation_command")
                    or runner.get("validation_command")
                    or ""
                ).strip(),
            }
        )

    action_rank = {
        "add_schema_mapping": 1,
        "patch_producer_script": 2,
        "endpoint_review": 3,
        "increase_timeout_with_cap": 4,
        "retry_after_fix": 5,
        "require_manual_file": 6,
        "leave_blocked_with_reason": 7,
    }

    retry_order_rows: list[dict[str, Any]] = []
    for row in sorted(
        remediation_rows,
        key=lambda item: (
            action_rank.get(str(item.get("next_action")), 99),
            _safe_int(item.get("priority")),
        ),
    ):
        retry_order_rows.append(
            {
                "retry_rank": len(retry_order_rows) + 1,
                "priority": row.get("priority"),
                "expected_input": row.get("expected_input"),
                "source_family": row.get("source_family"),
                "primary_blocker_class": row.get("primary_blocker_class"),
                "next_action": row.get("next_action"),
                "retry_instruction": f"{row.get('next_action')} -> retry_after_fix",
            }
        )

    _write_csv(
        exports_dir / "backfill_failure_remediation_matrix_r4_8c.csv",
        remediation_rows,
        [
            "priority",
            "expected_input",
            "source_family",
            "target_output_path",
            "terminal_status",
            "primary_blocker_class",
            "next_action",
            "reason",
            "producer_script",
            "source_url_or_portal",
            "required_env_vars",
            "missing_env_vars",
            "validation_command",
            "acceptance_gate",
            "recommended_action_r46",
            "forbidden_artifact_usage",
        ],
    )

    _write_csv(
        review_dir / "source_producer_fix_queue_r4_8c.csv",
        producer_fix_queue,
        [
            "priority",
            "expected_input",
            "source_family",
            "producer_script",
            "error_type",
            "stderr_excerpt_safe",
            "timeout_seconds",
            "recommended_patch",
            "next_action",
        ],
    )

    _write_csv(
        review_dir / "schema_remediation_queue_r4_8c.csv",
        schema_queue,
        [
            "priority",
            "expected_input",
            "source_family",
            "observed_columns",
            "required_columns",
            "missing_columns",
            "candidate_column_aliases",
            "recommended_mapping",
            "next_action",
        ],
    )

    _write_csv(
        review_dir / "manual_fallback_execution_queue_r4_8c.csv",
        manual_queue,
        [
            "priority",
            "source_family",
            "expected_input",
            "source_url_or_portal",
            "required_file_type",
            "accepted_filename_patterns",
            "required_columns",
            "target_dropzone_path",
            "target_output_path",
            "validation_command",
        ],
    )

    _write_csv(
        review_dir / "source_endpoint_review_queue_r4_8c.csv",
        endpoint_queue,
        [
            "priority",
            "expected_input",
            "source_family",
            "source_url_or_portal",
            "producer_script",
            "reason",
            "recommended_review",
            "next_action",
        ],
    )

    _write_csv(
        review_dir / "backfill_retry_order_r4_8c.csv",
        retry_order_rows,
        [
            "retry_rank",
            "priority",
            "expected_input",
            "source_family",
            "primary_blocker_class",
            "next_action",
            "retry_instruction",
        ],
    )

    blocker_counts = Counter(row.get("primary_blocker_class", "") for row in remediation_rows)

    status_payload = {
        "generated_at": _utc_now(),
        "r4_8c_phase_type": "SOURCE_BLOCKER_REMEDIATION_AND_MANUAL_FALLBACK_EXECUTION",
        "r4_8c_gate_passed": False,
        "r4_8c_total_failed_sources": len(failure_rows),
        "r4_8c_primary_blocker_counts": dict(sorted(blocker_counts.items())),
        "r4_8c_schema_remediation_count": len(schema_queue),
        "r4_8c_manual_fallback_count": len(manual_queue),
        "r4_8c_producer_fix_count": len(producer_fix_queue),
        "r4_8c_endpoint_review_count": len(endpoint_queue),
        "r4_8c_retry_order_count": len(retry_order_rows),
        "r4_8c_downloads_executed": False,
        "r4_8c_rows_ingested": 0,
        "r4_8c_production_inputs_staged": 0,
        "r4_8c_validated_source_manifests_written": 0,
        "r4_8c_retry_attempted": bool(retry_attempted),
        "r4_8c_retry_scope": str(retry_scope or ""),
        "r4_8c_retry_rows_ingested": 0,
        "r4_8c_retry_source_manifests_written": 0,
        "r4_8c_retry_failures": 0,
        "forbidden_artifact_usage": forbidden_artifact_usage,
        "row_fabrication_policy": row_fabrication_policy,
        "phase_7_8_blocked": True,
        "inputs": {
            "execution_results": "data/exports/controlled_backfill_execution_results_r4_8b.csv",
            "execution_status": "data/exports/controlled_backfill_execution_status_r4_8b.json",
            "execution_failures": "data/review_queue/controlled_backfill_execution_failures_r4_8b.csv",
            "schema_failures": "data/review_queue/schema_failures_r4_8b.csv",
            "manual_fallback": "data/review_queue/manual_fallback_required_r4_8b.csv",
            "readiness_matrix": "data/exports/backfill_readiness_matrix_r4_8a.csv",
            "backfill_execution_plan": "data/exports/backfill_execution_plan_r4_6.csv",
        },
        "outputs": {
            "remediation_matrix": "data/exports/backfill_failure_remediation_matrix_r4_8c.csv",
            "status": "data/exports/backfill_failure_remediation_status_r4_8c.json",
            "producer_fix_queue": "data/review_queue/source_producer_fix_queue_r4_8c.csv",
            "schema_remediation_queue": "data/review_queue/schema_remediation_queue_r4_8c.csv",
            "manual_fallback_execution_queue": "data/review_queue/manual_fallback_execution_queue_r4_8c.csv",
            "source_endpoint_review_queue": "data/review_queue/source_endpoint_review_queue_r4_8c.csv",
            "retry_order": "data/review_queue/backfill_retry_order_r4_8c.csv",
        },
    }

    all_classified = len(remediation_rows) == len(failure_rows) and all(
        row.get("primary_blocker_class") in PRIMARY_BLOCKER_CLASSES for row in remediation_rows
    )
    has_next_action = all(row.get("next_action") in NEXT_ACTIONS for row in remediation_rows)
    schema_queued = all(
        row.get("primary_blocker_class") != "schema_mismatch"
        or any(q.get("expected_input") == row.get("expected_input") for q in schema_queue)
        for row in remediation_rows
    )
    manual_queued = len(manual_queue) == len(manual_fallback_rows)
    producer_queued = all(
        row.get("primary_blocker_class") not in {"producer_timeout", "producer_exception", "endpoint_unavailable", "no_data"}
        or any(q.get("expected_input") == row.get("expected_input") for q in producer_fix_queue)
        for row in remediation_rows
    )

    status_payload["r4_8c_gate_passed"] = bool(
        all_classified
        and has_next_action
        and schema_queued
        and manual_queued
        and producer_queued
        and len(retry_order_rows) == len(remediation_rows)
        and not forbidden_artifact_usage
        and row_fabrication_policy == "FORBIDDEN_NO_SYNTHETIC_ROWS"
        and status_payload["phase_7_8_blocked"] is True
    )

    _write_json(exports_dir / "backfill_failure_remediation_status_r4_8c.json", status_payload)

    next_rebuild_status = dict(rebuild_status)
    next_rebuild_status.update(
        {
            "r4_8c_generated_at": status_payload["generated_at"],
            "r4_8c_phase_type": status_payload["r4_8c_phase_type"],
            "r4_8c_gate_passed": status_payload["r4_8c_gate_passed"],
            "r4_8c_total_failed_sources": status_payload["r4_8c_total_failed_sources"],
            "r4_8c_primary_blocker_counts": status_payload["r4_8c_primary_blocker_counts"],
            "r4_8c_schema_remediation_count": status_payload["r4_8c_schema_remediation_count"],
            "r4_8c_manual_fallback_count": status_payload["r4_8c_manual_fallback_count"],
            "r4_8c_producer_fix_count": status_payload["r4_8c_producer_fix_count"],
            "r4_8c_endpoint_review_count": status_payload["r4_8c_endpoint_review_count"],
            "r4_8c_retry_order_count": status_payload["r4_8c_retry_order_count"],
            "r4_8c_downloads_executed": status_payload["r4_8c_downloads_executed"],
            "r4_8c_rows_ingested": status_payload["r4_8c_rows_ingested"],
            "r4_8c_production_inputs_staged": status_payload["r4_8c_production_inputs_staged"],
            "r4_8c_validated_source_manifests_written": status_payload[
                "r4_8c_validated_source_manifests_written"
            ],
            "row_fabrication_policy": row_fabrication_policy,
            "phase_7_8_blocked": True,
            "r4_8c_outputs": status_payload["outputs"],
        }
    )
    _write_json(exports_dir / "rebuild_status.json", next_rebuild_status)

    return status_payload
