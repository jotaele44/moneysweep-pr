"""R4.8D targeted producer patches and schema-alignment retry runner."""

from __future__ import annotations

import csv
import hashlib
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from contract_sweeper.pipeline.schema_alignment import align_source_schema, split_pipe

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

ACTIONABLE_BLOCKERS = {"producer_exception", "schema_mismatch", "no_data"}

PATCHABLE_SCRIPTS_ALLOW_EMPTY = {
    "scripts/download_subawards.py",
    "scripts/download_sba.py",
    "scripts/download_sbir.py",
    "scripts/download_usace_civil.py",
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
            import pandas as pd

            return int(len(pd.read_parquet(path)))
    except Exception:
        return 0
    return 0


def _stderr_excerpt_safe(text: str, max_len: int = 240) -> str:
    cleaned = str(text or "").replace("\n", " ").replace("\r", " ").strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned[:max_len]


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
            timeout=timeout_s,
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
    return False, int(completed.returncode), excerpt or f"command failed with exit code {completed.returncode}"


def _patch_retry_command(command: str, producer_script: str) -> tuple[str, bool]:
    cmd = str(command or "").strip()
    if not cmd:
        return "", False

    if producer_script in PATCHABLE_SCRIPTS_ALLOW_EMPTY and "--allow-empty-success" not in cmd:
        return f"{cmd} --allow-empty-success", True

    return cmd, False


def _manifest_relpath(priority: int, expected_input: str) -> str:
    stem = Path(expected_input).stem or "source"
    safe = "".join(ch if ch.isalnum() else "_" for ch in stem).strip("_") or "source"
    return f"data/manifests/r4_8d/{priority:02d}_{safe}.manifest.json"


def _write_manifest(
    root: Path,
    *,
    priority: int,
    source_system: str,
    source_file: str,
    target_output_path: str,
    row_count: int,
    producer_script: str,
) -> dict[str, Any]:
    target_abs = root / target_output_path
    payload = {
        "source_system": source_system,
        "source_file": source_file,
        "target_output_path": target_output_path,
        "row_count": int(row_count),
        "sha256": _sha256(target_abs),
        "generated_at": _utc_now(),
        "producer_script": producer_script,
        "validation_status": "validated",
        "known_gaps": "",
        "schema_version": "r4_8d_schema_v1",
        "manifest_type": "validated_source_manifest",
    }

    relpath = _manifest_relpath(priority, source_file)
    path = root / relpath
    _write_json(path, payload)

    row = dict(payload)
    row["manifest_path"] = relpath
    return row


def run_targeted_backfill_retry(
    root: Path,
    *,
    command_timeout_s: int = 30,
    validation_timeout_s: int = 30,
) -> dict[str, Any]:
    root = Path(root)
    exports_dir = root / "data" / "exports"
    review_dir = root / "data" / "review_queue"

    remediation_rows = _read_csv(exports_dir / "backfill_failure_remediation_matrix_r4_8c.csv")
    remediation_status = _read_json(exports_dir / "backfill_failure_remediation_status_r4_8c.json")
    producer_fix_queue = _read_csv(review_dir / "source_producer_fix_queue_r4_8c.csv")
    schema_queue = _read_csv(review_dir / "schema_remediation_queue_r4_8c.csv")
    manual_queue = _read_csv(review_dir / "manual_fallback_execution_queue_r4_8c.csv")
    endpoint_queue = _read_csv(review_dir / "source_endpoint_review_queue_r4_8c.csv")
    retry_order_r48c = _read_csv(review_dir / "backfill_retry_order_r4_8c.csv")
    results_r48b = _read_csv(exports_dir / "controlled_backfill_execution_results_r4_8b.csv")
    rebuild_status = _read_json(exports_dir / "rebuild_status.json")

    row_fabrication_policy = str(
        rebuild_status.get("row_fabrication_policy")
        or remediation_status.get("row_fabrication_policy")
        or "FORBIDDEN_NO_SYNTHETIC_ROWS"
    )

    results_r48b_by_input = {
        str(row.get("expected_input", "")).strip(): row
        for row in results_r48b
        if str(row.get("expected_input", "")).strip()
    }
    schema_by_input = {
        str(row.get("expected_input", "")).strip(): row
        for row in schema_queue
        if str(row.get("expected_input", "")).strip()
    }
    manual_by_input = {
        str(row.get("expected_input", "")).strip(): row
        for row in manual_queue
        if str(row.get("expected_input", "")).strip()
    }
    endpoint_inputs = {
        str(row.get("expected_input", "")).strip()
        for row in endpoint_queue
        if str(row.get("expected_input", "")).strip()
    }
    retry_rank_by_input = {
        str(row.get("expected_input", "")).strip(): _safe_int(row.get("retry_rank"))
        for row in retry_order_r48c
    }

    targeted_results: list[dict[str, Any]] = []
    schema_alignment_report: list[dict[str, Any]] = []
    validated_manifests: list[dict[str, Any]] = []

    unresolved_producer: list[dict[str, Any]] = []
    unresolved_schema: list[dict[str, Any]] = []
    unresolved_endpoint: list[dict[str, Any]] = []
    manual_fallback_remaining: list[dict[str, Any]] = []

    retry_order_r48d: list[dict[str, Any]] = []

    forbidden_artifact_usage = False
    sources_retried = 0
    successful_sources = 0
    failed_sources = 0
    rows_ingested = 0
    production_inputs_staged = 0
    producer_patch_hits = 0

    patched_script_ids = {
        row.get("producer_script", "")
        for row in producer_fix_queue
        if row.get("producer_script", "") in PATCHABLE_SCRIPTS_ALLOW_EMPTY
    }

    for remediation in sorted(remediation_rows, key=lambda r: _safe_int(r.get("priority"))):
        priority = _safe_int(remediation.get("priority"))
        expected_input = str(remediation.get("expected_input", "")).strip()
        source_family = str(remediation.get("source_family", "")).strip()
        target_output_path = str(remediation.get("target_output_path") or expected_input).strip()
        primary_blocker = str(remediation.get("primary_blocker_class", "")).strip()
        producer_script = str(remediation.get("producer_script", "")).strip()
        next_action = str(remediation.get("next_action", "")).strip()

        previous = results_r48b_by_input.get(expected_input, {})
        command = str(previous.get("command", "")).strip()
        validation_command = str(
            remediation.get("validation_command")
            or previous.get("validation_command")
            or ""
        ).strip()

        required_columns = str(
            schema_by_input.get(expected_input, {}).get("required_columns")
            or manual_by_input.get(expected_input, {}).get("required_columns")
            or ""
        ).strip()
        recommended_mapping = str(schema_by_input.get(expected_input, {}).get("recommended_mapping") or "")

        forbidden_for_source = bool(
            _contains_forbidden_token(expected_input)
            or _contains_forbidden_token(target_output_path)
        )
        forbidden_artifact_usage = bool(forbidden_artifact_usage or forbidden_for_source)

        retry_eligible = primary_blocker in ACTIONABLE_BLOCKERS and not forbidden_for_source

        row_result: dict[str, Any] = {
            "priority": priority,
            "retry_rank": retry_rank_by_input.get(expected_input, 0),
            "expected_input": expected_input,
            "source_family": source_family,
            "primary_blocker_class": primary_blocker,
            "next_action": next_action,
            "retry_eligible": retry_eligible,
            "retry_attempted": False,
            "retry_status": "not_retried",
            "target_output_path": target_output_path,
            "row_count": 0,
            "validation_status": "not_run",
            "manifest_written": False,
            "failure_reason": "",
            "producer_script": producer_script,
            "command": command,
            "patched_command": "",
            "command_exit_code": "",
            "command_excerpt_safe": "",
            "schema_alignment_status": "not_applicable",
            "schema_alignment_added_count": 0,
            "forbidden_artifact_usage": forbidden_for_source,
            "manual_fallback_required": True,
            "disposition": "manual_fallback_remaining",
        }

        if forbidden_for_source:
            row_result["retry_status"] = "blocked_forbidden_artifact"
            row_result["failure_reason"] = "forbidden artifact token detected"
        elif not retry_eligible:
            if primary_blocker == "endpoint_unavailable":
                row_result["retry_status"] = "not_retried_endpoint_unavailable"
                row_result["failure_reason"] = "endpoint unavailable source left queued"
            else:
                row_result["retry_status"] = "not_retried_non_actionable"
                row_result["failure_reason"] = "source left queued by remediation plan"
        else:
            sources_retried += 1
            row_result["retry_attempted"] = True

            patched_command, patched = _patch_retry_command(command, producer_script)
            row_result["patched_command"] = patched_command
            if patched:
                producer_patch_hits += 1

            if not patched_command:
                row_result["retry_status"] = "failed_missing_command"
                row_result["failure_reason"] = "missing producer command"
            elif primary_blocker == "endpoint_unavailable" and expected_input in endpoint_inputs and not patched:
                row_result["retry_status"] = "skipped_endpoint_unpatched"
                row_result["failure_reason"] = "endpoint-unavailable source not retried without patch"
            else:
                ok, exit_code, excerpt = _run_command(root, patched_command, command_timeout_s)
                row_result["command_exit_code"] = str(exit_code)
                row_result["command_excerpt_safe"] = excerpt

                if not ok:
                    row_result["retry_status"] = "failed_command"
                    row_result["failure_reason"] = excerpt or f"command failed with exit code {exit_code}"
                else:
                    target_abs = root / target_output_path
                    row_count = _record_count(target_abs)
                    row_result["row_count"] = row_count
                    if row_count <= 0:
                        row_result["retry_status"] = "failed_no_data"
                        row_result["failure_reason"] = "target output has zero rows"
                    else:
                        align_report = align_source_schema(
                            root,
                            expected_input=expected_input,
                            target_output_path=target_output_path,
                            source_family=source_family,
                            required_columns_raw=required_columns,
                            recommended_mapping_raw=recommended_mapping,
                        )
                        schema_alignment_report.append(align_report)

                        row_result["schema_alignment_status"] = align_report.get("alignment_status", "")
                        row_result["schema_alignment_added_count"] = int(
                            align_report.get("alignment_added_count", 0) or 0
                        )

                        if _to_bool(align_report.get("forbidden_artifact_usage")):
                            row_result["retry_status"] = "failed_forbidden_artifact"
                            row_result["failure_reason"] = str(align_report.get("failure_reason", ""))
                            forbidden_artifact_usage = True
                        elif str(align_report.get("missing_columns_after", "")).strip():
                            row_result["retry_status"] = "failed_schema"
                            row_result["failure_reason"] = str(
                                align_report.get("failure_reason")
                                or "required schema unresolved after alignment"
                            )
                        else:
                            if validation_command:
                                valid_ok, valid_exit, valid_excerpt = _run_command(
                                    root,
                                    validation_command,
                                    validation_timeout_s,
                                )
                                row_result["validation_status"] = "passed" if valid_ok else "failed"
                                if not valid_ok:
                                    row_result["retry_status"] = "failed_validation"
                                    row_result["failure_reason"] = valid_excerpt or f"validation failed ({valid_exit})"
                                else:
                                    row_result["retry_status"] = "success"
                            else:
                                row_result["validation_status"] = "schema_only_passed"
                                row_result["retry_status"] = "success"

                            if row_result["retry_status"] == "success":
                                manifest_row = _write_manifest(
                                    root,
                                    priority=priority,
                                    source_system=source_family,
                                    source_file=expected_input,
                                    target_output_path=target_output_path,
                                    row_count=row_count,
                                    producer_script=producer_script,
                                )
                                validated_manifests.append(manifest_row)
                                row_result["manifest_written"] = True
                                row_result["manual_fallback_required"] = False
                                row_result["disposition"] = "fixed_and_retried"
                                successful_sources += 1
                                rows_ingested += row_count
                                production_inputs_staged += 1

        if row_result["retry_status"] != "success":
            failed_sources += 1 if row_result["retry_attempted"] else 0
            if primary_blocker == "endpoint_unavailable":
                unresolved_endpoint.append(
                    {
                        "priority": priority,
                        "expected_input": expected_input,
                        "source_family": source_family,
                        "retry_status": row_result["retry_status"],
                        "failure_reason": row_result["failure_reason"],
                        "next_action": "endpoint_review",
                    }
                )
            if primary_blocker == "schema_mismatch":
                unresolved_schema.append(
                    {
                        "priority": priority,
                        "expected_input": expected_input,
                        "source_family": source_family,
                        "retry_status": row_result["retry_status"],
                        "failure_reason": row_result["failure_reason"],
                        "required_columns": required_columns,
                        "next_action": "manual_fallback_or_schema_patch",
                    }
                )
            if primary_blocker in {"producer_exception", "no_data"}:
                unresolved_producer.append(
                    {
                        "priority": priority,
                        "expected_input": expected_input,
                        "source_family": source_family,
                        "producer_script": producer_script,
                        "retry_status": row_result["retry_status"],
                        "failure_reason": row_result["failure_reason"],
                        "next_action": "producer_patch_or_manual_fallback",
                    }
                )

            manual_fallback_remaining.append(
                {
                    "priority": priority,
                    "expected_input": expected_input,
                    "source_family": source_family,
                    "retry_status": row_result["retry_status"],
                    "failure_reason": row_result["failure_reason"],
                    "target_output_path": target_output_path,
                    "next_action": "manual_fallback_required",
                }
            )

        targeted_results.append(row_result)

        retry_order_r48d.append(
            {
                "retry_rank": row_result["retry_rank"],
                "priority": priority,
                "expected_input": expected_input,
                "source_family": source_family,
                "primary_blocker_class": primary_blocker,
                "retry_attempted": row_result["retry_attempted"],
                "retry_status": row_result["retry_status"],
                "disposition": row_result["disposition"],
                "next_action": "manual_fallback_required"
                if row_result["retry_status"] != "success"
                else "ready_for_master_rebuild_gate",
            }
        )

    schema_alignments_added = sum(
        int(row.get("schema_alignment_added_count", 0) or 0) for row in targeted_results
    )

    manifests_written = len(validated_manifests)
    unresolved_endpoint_count = len(unresolved_endpoint)
    unresolved_schema_count = len(unresolved_schema)
    unresolved_producer_count = len(unresolved_producer)
    manual_fallback_remaining_count = len(manual_fallback_remaining)

    _write_csv(
        exports_dir / "targeted_backfill_retry_results_r4_8d.csv",
        targeted_results,
        [
            "priority",
            "retry_rank",
            "expected_input",
            "source_family",
            "primary_blocker_class",
            "next_action",
            "retry_eligible",
            "retry_attempted",
            "retry_status",
            "target_output_path",
            "row_count",
            "validation_status",
            "manifest_written",
            "failure_reason",
            "producer_script",
            "command",
            "patched_command",
            "command_exit_code",
            "command_excerpt_safe",
            "schema_alignment_status",
            "schema_alignment_added_count",
            "forbidden_artifact_usage",
            "manual_fallback_required",
            "disposition",
        ],
    )

    _write_csv(
        exports_dir / "schema_alignment_report_r4_8d.csv",
        schema_alignment_report,
        [
            "expected_input",
            "target_output_path",
            "source_family",
            "alignment_attempted",
            "alignment_applied",
            "deterministic_mapping",
            "forbidden_artifact_usage",
            "row_count",
            "observed_columns_before",
            "observed_columns_after",
            "required_columns",
            "missing_columns_before",
            "missing_columns_after",
            "applied_mapping",
            "alignment_added_count",
            "alignment_status",
            "failure_reason",
        ],
    )

    _write_csv(
        exports_dir / "validated_source_manifest_inventory_r4_8d.csv",
        validated_manifests,
        [
            "source_system",
            "source_file",
            "target_output_path",
            "row_count",
            "sha256",
            "generated_at",
            "producer_script",
            "validation_status",
            "known_gaps",
            "schema_version",
            "manifest_type",
            "manifest_path",
        ],
    )

    _write_csv(
        review_dir / "unresolved_producer_failures_r4_8d.csv",
        unresolved_producer,
        [
            "priority",
            "expected_input",
            "source_family",
            "producer_script",
            "retry_status",
            "failure_reason",
            "next_action",
        ],
    )
    _write_csv(
        review_dir / "unresolved_schema_failures_r4_8d.csv",
        unresolved_schema,
        [
            "priority",
            "expected_input",
            "source_family",
            "retry_status",
            "failure_reason",
            "required_columns",
            "next_action",
        ],
    )
    _write_csv(
        review_dir / "unresolved_endpoint_failures_r4_8d.csv",
        unresolved_endpoint,
        [
            "priority",
            "expected_input",
            "source_family",
            "retry_status",
            "failure_reason",
            "next_action",
        ],
    )
    _write_csv(
        review_dir / "manual_fallback_remaining_r4_8d.csv",
        manual_fallback_remaining,
        [
            "priority",
            "expected_input",
            "source_family",
            "retry_status",
            "failure_reason",
            "target_output_path",
            "next_action",
        ],
    )
    _write_csv(
        review_dir / "backfill_retry_order_r4_8d.csv",
        sorted(retry_order_r48d, key=lambda r: (_safe_int(r.get("retry_rank")), _safe_int(r.get("priority")))),
        [
            "retry_rank",
            "priority",
            "expected_input",
            "source_family",
            "primary_blocker_class",
            "retry_attempted",
            "retry_status",
            "disposition",
            "next_action",
        ],
    )

    total_sources = len(remediation_rows)
    phase_7_8_blocked = True

    # all sources accounted for in result matrix
    all_accounted = len(targeted_results) == total_sources
    consumed_queues = bool(
        remediation_rows
        and producer_fix_queue is not None
        and schema_queue is not None
        and manual_queue is not None
        and endpoint_queue is not None
        and retry_order_r48c is not None
    )
    all_have_disposition = all(
        str(row.get("disposition", "")).strip() in {"fixed_and_retried", "manual_fallback_remaining"}
        for row in targeted_results
    )
    staged_with_manifest = all(
        (row.get("retry_status") != "success") or _to_bool(row.get("manifest_written"))
        for row in targeted_results
    )
    deterministic_schema_recorded = all(
        row.get("primary_blocker_class") != "schema_mismatch"
        or any(r.get("expected_input") == row.get("expected_input") for r in schema_alignment_report)
        for row in targeted_results
    )

    status_payload = {
        "generated_at": _utc_now(),
        "r4_8d_phase_type": "TARGETED_PRODUCER_PATCHES_AND_SCHEMA_ALIGNMENT_RETRY",
        "r4_8d_gate_passed": False,
        "r4_8d_total_sources_considered": total_sources,
        "r4_8d_sources_retried": sources_retried,
        "r4_8d_successful_sources": successful_sources,
        "r4_8d_failed_sources": failed_sources,
        "r4_8d_schema_alignments_added": schema_alignments_added,
        "r4_8d_producer_patches_applied": len(patched_script_ids | set()) if patched_script_ids else producer_patch_hits,
        "r4_8d_rows_ingested": rows_ingested,
        "r4_8d_production_inputs_staged": production_inputs_staged,
        "r4_8d_validated_source_manifests_written": manifests_written,
        "r4_8d_manual_fallback_remaining": manual_fallback_remaining_count,
        "r4_8d_unresolved_endpoint_failures": unresolved_endpoint_count,
        "r4_8d_unresolved_schema_failures": unresolved_schema_count,
        "r4_8d_unresolved_producer_failures": unresolved_producer_count,
        "r4_8d_forbidden_artifact_usage": forbidden_artifact_usage,
        "row_fabrication_policy": row_fabrication_policy,
        "phase_7_8_blocked": phase_7_8_blocked,
        "inputs": {
            "remediation_matrix": "data/exports/backfill_failure_remediation_matrix_r4_8c.csv",
            "remediation_status": "data/exports/backfill_failure_remediation_status_r4_8c.json",
            "producer_fix_queue": "data/review_queue/source_producer_fix_queue_r4_8c.csv",
            "schema_remediation_queue": "data/review_queue/schema_remediation_queue_r4_8c.csv",
            "manual_fallback_queue": "data/review_queue/manual_fallback_execution_queue_r4_8c.csv",
            "endpoint_review_queue": "data/review_queue/source_endpoint_review_queue_r4_8c.csv",
            "retry_order_r4_8c": "data/review_queue/backfill_retry_order_r4_8c.csv",
            "execution_results_r4_8b": "data/exports/controlled_backfill_execution_results_r4_8b.csv",
        },
        "outputs": {
            "targeted_retry_results": "data/exports/targeted_backfill_retry_results_r4_8d.csv",
            "targeted_retry_status": "data/exports/targeted_backfill_retry_status_r4_8d.json",
            "schema_alignment_report": "data/exports/schema_alignment_report_r4_8d.csv",
            "validated_manifest_inventory": "data/exports/validated_source_manifest_inventory_r4_8d.csv",
            "unresolved_producer": "data/review_queue/unresolved_producer_failures_r4_8d.csv",
            "unresolved_schema": "data/review_queue/unresolved_schema_failures_r4_8d.csv",
            "unresolved_endpoint": "data/review_queue/unresolved_endpoint_failures_r4_8d.csv",
            "manual_fallback_remaining": "data/review_queue/manual_fallback_remaining_r4_8d.csv",
            "retry_order_r4_8d": "data/review_queue/backfill_retry_order_r4_8d.csv",
        },
    }

    status_payload["r4_8d_gate_passed"] = bool(
        all_accounted
        and consumed_queues
        and all_have_disposition
        and deterministic_schema_recorded
        and staged_with_manifest
        and not forbidden_artifact_usage
        and row_fabrication_policy == "FORBIDDEN_NO_SYNTHETIC_ROWS"
        and phase_7_8_blocked
    )

    _write_json(exports_dir / "targeted_backfill_retry_status_r4_8d.json", status_payload)

    next_rebuild_status = dict(rebuild_status)
    next_rebuild_status.update(
        {
            "r4_8d_generated_at": status_payload["generated_at"],
            "r4_8d_phase_type": status_payload["r4_8d_phase_type"],
            "r4_8d_gate_passed": status_payload["r4_8d_gate_passed"],
            "r4_8d_total_sources_considered": status_payload["r4_8d_total_sources_considered"],
            "r4_8d_sources_retried": status_payload["r4_8d_sources_retried"],
            "r4_8d_successful_sources": status_payload["r4_8d_successful_sources"],
            "r4_8d_failed_sources": status_payload["r4_8d_failed_sources"],
            "r4_8d_schema_alignments_added": status_payload["r4_8d_schema_alignments_added"],
            "r4_8d_producer_patches_applied": status_payload["r4_8d_producer_patches_applied"],
            "r4_8d_rows_ingested": status_payload["r4_8d_rows_ingested"],
            "r4_8d_production_inputs_staged": status_payload["r4_8d_production_inputs_staged"],
            "r4_8d_validated_source_manifests_written": status_payload[
                "r4_8d_validated_source_manifests_written"
            ],
            "r4_8d_manual_fallback_remaining": status_payload["r4_8d_manual_fallback_remaining"],
            "r4_8d_unresolved_endpoint_failures": status_payload["r4_8d_unresolved_endpoint_failures"],
            "r4_8d_unresolved_schema_failures": status_payload["r4_8d_unresolved_schema_failures"],
            "r4_8d_unresolved_producer_failures": status_payload[
                "r4_8d_unresolved_producer_failures"
            ],
            "r4_8d_forbidden_artifact_usage": status_payload["r4_8d_forbidden_artifact_usage"],
            "row_fabrication_policy": row_fabrication_policy,
            "phase_7_8_blocked": True,
            "r4_8d_outputs": status_payload["outputs"],
        }
    )
    _write_json(exports_dir / "rebuild_status.json", next_rebuild_status)

    return status_payload
