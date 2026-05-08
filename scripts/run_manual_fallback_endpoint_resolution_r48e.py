"""Run R4.8E manual fallback + endpoint/producer resolution execution."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from contract_sweeper.pipeline.endpoint_resolution import review_endpoint_failures
from contract_sweeper.pipeline.manual_fallback_package import (
    build_manual_fallback_package,
    contains_forbidden_token,
    safe_int,
)
from contract_sweeper.pipeline.producer_failure_resolution import review_producer_failures


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


def _next_action_for_source(
    *,
    expected_input: str,
    manual_by_input: dict[str, dict[str, Any]],
    endpoint_by_input: dict[str, dict[str, Any]],
    producer_by_input: dict[str, dict[str, Any]],
) -> str:
    endpoint_row = endpoint_by_input.get(expected_input)
    producer_row = producer_by_input.get(expected_input)
    manual_row = manual_by_input.get(expected_input)

    if endpoint_row:
        return str(endpoint_row.get("next_action", "manual_endpoint_triage"))
    if producer_row:
        return str(producer_row.get("next_action", "leave_blocked_with_reason"))
    if manual_row:
        return str(manual_row.get("next_action", "require_manual_file"))
    return "leave_blocked_with_reason"


def _contains_forbidden_artifact(paths: list[str]) -> bool:
    for path in paths:
        if contains_forbidden_token(path):
            return True
        lowered = str(path or "").lower()
        if any(token in lowered for token in FORBIDDEN_ARTIFACT_TOKENS):
            return True
    return False


def run_manual_fallback_endpoint_resolution(
    root: Path,
    *,
    enable_endpoint_probes: bool = True,
    probe_timeout_seconds: int = 6,
) -> dict[str, Any]:
    root = Path(root)
    exports_dir = root / "data" / "exports"
    review_dir = root / "data" / "review_queue"

    status_r48d = _read_json(exports_dir / "targeted_backfill_retry_status_r4_8d.json")
    retry_results = _read_csv(exports_dir / "targeted_backfill_retry_results_r4_8d.csv")
    validated_manifest_inventory = _read_csv(exports_dir / "validated_source_manifest_inventory_r4_8d.csv")
    manual_rows = _read_csv(review_dir / "manual_fallback_remaining_r4_8d.csv")
    endpoint_rows = _read_csv(review_dir / "unresolved_endpoint_failures_r4_8d.csv")
    producer_rows = _read_csv(review_dir / "unresolved_producer_failures_r4_8d.csv")
    retry_order_rows = _read_csv(review_dir / "backfill_retry_order_r4_8d.csv")
    rebuild_status = _read_json(exports_dir / "rebuild_status.json")
    runner_manifest_rows = _read_csv(exports_dir / "backfill_runner_manifest_r4_7.csv")

    retry_results_by_input = {
        str(row.get("expected_input", "")).strip(): row
        for row in retry_results
        if str(row.get("expected_input", "")).strip()
    }
    runner_manifest_by_input = {
        str(row.get("expected_input", "")).strip(): row
        for row in runner_manifest_rows
        if str(row.get("expected_input", "")).strip()
    }

    manual_payload, manual_inventory_rows, manual_required_rows, manual_forbidden = (
        build_manual_fallback_package(
            manual_rows=manual_rows,
            runner_manifest_by_input=runner_manifest_by_input,
            retry_results_by_input=retry_results_by_input,
        )
    )

    endpoint_report_rows, endpoint_followup_rows = review_endpoint_failures(
        endpoint_rows=endpoint_rows,
        runner_manifest_by_input=runner_manifest_by_input,
        probe_timeout_seconds=max(1, int(probe_timeout_seconds)),
        enable_probes=bool(enable_endpoint_probes),
    )
    endpoint_by_input = {
        str(row.get("expected_input", "")).strip(): row for row in endpoint_report_rows
    }

    producer_report_rows, producer_patch_remaining_rows = review_producer_failures(
        producer_rows=producer_rows,
        retry_results_by_input=retry_results_by_input,
        endpoint_report_by_input=endpoint_by_input,
    )
    producer_by_input = {
        str(row.get("expected_input", "")).strip(): row for row in producer_report_rows
    }

    manual_by_input = {
        str(row.get("expected_input", "")).strip(): row for row in manual_required_rows
    }

    unresolved_inputs: dict[str, dict[str, Any]] = {}
    for collection in (manual_rows, endpoint_rows, producer_rows):
        for row in collection:
            expected_input = str(row.get("expected_input", "")).strip()
            if not expected_input:
                continue
            current = unresolved_inputs.setdefault(expected_input, dict(row))
            if "priority" not in current or not str(current.get("priority", "")).strip():
                current["priority"] = row.get("priority", "")

    retry_rank_by_input = {
        str(row.get("expected_input", "")).strip(): safe_int(row.get("retry_rank"))
        for row in retry_order_rows
        if str(row.get("expected_input", "")).strip()
    }

    retry_order_r48e: list[dict[str, Any]] = []
    for expected_input, base_row in sorted(
        unresolved_inputs.items(),
        key=lambda item: (
            safe_int(item[1].get("priority")),
            retry_rank_by_input.get(item[0], 0),
            item[0],
        ),
    ):
        source_family = str(
            base_row.get("source_family")
            or runner_manifest_by_input.get(expected_input, {}).get("source_family")
            or "unknown_source"
        ).strip()
        endpoint_classification = str(
            endpoint_by_input.get(expected_input, {}).get("endpoint_classification", "")
        ).strip()
        producer_classification = str(
            producer_by_input.get(expected_input, {}).get("producer_classification", "")
        ).strip()
        next_action = _next_action_for_source(
            expected_input=expected_input,
            manual_by_input=manual_by_input,
            endpoint_by_input=endpoint_by_input,
            producer_by_input=producer_by_input,
        )

        retry_order_r48e.append(
            {
                "retry_rank": len(retry_order_r48e) + 1,
                "priority": base_row.get("priority", ""),
                "expected_input": expected_input,
                "source_family": source_family,
                "endpoint_classification": endpoint_classification,
                "producer_classification": producer_classification,
                "next_action": next_action,
            }
        )

    manual_fallback_sources = len(manual_inventory_rows)
    endpoint_failures_reviewed = len(endpoint_report_rows)
    producer_failures_reviewed = len(producer_report_rows)
    manual_files_required = len(manual_required_rows)
    endpoint_followup_required = len(endpoint_followup_rows)
    producer_patch_remaining = len(producer_patch_remaining_rows)

    rows_ingested = safe_int(
        status_r48d.get("r4_8d_rows_ingested", rebuild_status.get("r4_8d_rows_ingested", 0))
    )
    production_inputs_staged = safe_int(
        status_r48d.get(
            "r4_8d_production_inputs_staged",
            rebuild_status.get("r4_8d_production_inputs_staged", 0),
        )
    )
    validated_source_manifests_written = safe_int(
        status_r48d.get(
            "r4_8d_validated_source_manifests_written",
            rebuild_status.get("r4_8d_validated_source_manifests_written", len(validated_manifest_inventory)),
        )
    )

    row_fabrication_policy = str(
        rebuild_status.get("row_fabrication_policy")
        or status_r48d.get("row_fabrication_policy")
        or "FORBIDDEN_NO_SYNTHETIC_ROWS"
    )
    phase_7_8_blocked = bool(
        rebuild_status.get("phase_7_8_blocked", status_r48d.get("phase_7_8_blocked", True))
    )

    forbidden_artifact_usage = bool(
        manual_forbidden
        or _contains_forbidden_artifact(
            [
                row.get("expected_input", "")
                for row in manual_inventory_rows + endpoint_report_rows + producer_report_rows
            ]
        )
    )

    manual_rows_have_required_fields = all(
        bool(str(row.get("target_dropzone_path", "")).strip())
        and bool(str(row.get("accepted_filename_patterns", "")).strip())
        and bool(str(row.get("required_columns", "")).strip())
        and bool(str(row.get("target_output_path", "")).strip())
        and bool(str(row.get("validation_command", "")).strip())
        for row in manual_inventory_rows
    )
    endpoint_rows_classified = all(
        bool(str(row.get("endpoint_classification", "")).strip()) for row in endpoint_report_rows
    )
    producer_rows_classified = all(
        bool(str(row.get("producer_classification", "")).strip()) for row in producer_report_rows
    )
    all_unresolved_have_next_action = all(
        bool(str(row.get("next_action", "")).strip()) for row in retry_order_r48e
    )

    status_payload = {
        "generated_at": _utc_now(),
        "r4_8e_phase_type": "MANUAL_FALLBACK_AND_ENDPOINT_RESOLUTION_EXECUTION",
        "r4_8e_gate_passed": False,
        "r4_8e_manual_fallback_sources": manual_fallback_sources,
        "r4_8e_endpoint_failures_reviewed": endpoint_failures_reviewed,
        "r4_8e_producer_failures_reviewed": producer_failures_reviewed,
        "r4_8e_manual_files_required": manual_files_required,
        "r4_8e_endpoint_followup_required": endpoint_followup_required,
        "r4_8e_producer_patch_remaining": producer_patch_remaining,
        "r4_8e_rows_ingested": rows_ingested,
        "r4_8e_production_inputs_staged": production_inputs_staged,
        "r4_8e_validated_source_manifests_written": validated_source_manifests_written,
        "r4_8e_forbidden_artifact_usage": forbidden_artifact_usage,
        "r4_8e_narrow_endpoint_probes_enabled": bool(enable_endpoint_probes),
        "r4_8e_downloads_executed": False,
        "row_fabrication_policy": row_fabrication_policy,
        "phase_7_8_blocked": phase_7_8_blocked,
        "inputs": {
            "targeted_retry_status": "data/exports/targeted_backfill_retry_status_r4_8d.json",
            "targeted_retry_results": "data/exports/targeted_backfill_retry_results_r4_8d.csv",
            "validated_manifest_inventory": "data/exports/validated_source_manifest_inventory_r4_8d.csv",
            "manual_fallback_remaining": "data/review_queue/manual_fallback_remaining_r4_8d.csv",
            "unresolved_endpoint_failures": "data/review_queue/unresolved_endpoint_failures_r4_8d.csv",
            "unresolved_producer_failures": "data/review_queue/unresolved_producer_failures_r4_8d.csv",
            "backfill_retry_order_r4_8d": "data/review_queue/backfill_retry_order_r4_8d.csv",
        },
        "outputs": {
            "manual_fallback_package": "data/exports/manual_fallback_package_r4_8e.json",
            "manual_fallback_inventory": "data/exports/manual_fallback_inventory_r4_8e.csv",
            "endpoint_resolution_report": "data/exports/endpoint_resolution_report_r4_8e.csv",
            "producer_failure_resolution_report": "data/exports/producer_failure_resolution_report_r4_8e.csv",
            "manual_files_required": "data/review_queue/manual_files_required_r4_8e.csv",
            "endpoint_followup_required": "data/review_queue/endpoint_followup_required_r4_8e.csv",
            "producer_patch_remaining": "data/review_queue/producer_patch_remaining_r4_8e.csv",
            "retry_order_r4_8e": "data/review_queue/backfill_retry_order_r4_8e.csv",
        },
    }

    gate_passed = (
        all_unresolved_have_next_action
        and manual_rows_have_required_fields
        and endpoint_rows_classified
        and producer_rows_classified
        and not forbidden_artifact_usage
        and row_fabrication_policy == "FORBIDDEN_NO_SYNTHETIC_ROWS"
        and phase_7_8_blocked
    )
    status_payload["r4_8e_gate_passed"] = bool(gate_passed)

    _write_json(exports_dir / "manual_fallback_package_r4_8e.json", manual_payload)
    _write_csv(
        exports_dir / "manual_fallback_inventory_r4_8e.csv",
        manual_inventory_rows,
        [
            "priority",
            "source_family",
            "expected_input",
            "required_file_type",
            "accepted_filename_patterns",
            "required_columns",
            "target_dropzone_path",
            "target_output_path",
            "validation_command",
            "source_url_or_portal",
            "manual_export_steps",
            "producer_script",
            "required_env_vars",
            "retry_status",
            "failure_reason",
            "next_action",
            "forbidden_artifact_usage",
        ],
    )
    _write_csv(
        exports_dir / "endpoint_resolution_report_r4_8e.csv",
        endpoint_report_rows,
        [
            "priority",
            "expected_input",
            "source_family",
            "producer_script",
            "source_url_or_portal",
            "failure_reason",
            "endpoint_classification",
            "next_action",
            "probe_attempted",
            "probe_ok",
            "probe_status_code",
            "probe_error",
        ],
    )
    _write_csv(
        exports_dir / "producer_failure_resolution_report_r4_8e.csv",
        producer_report_rows,
        [
            "priority",
            "expected_input",
            "source_family",
            "producer_script",
            "retry_status",
            "failure_reason",
            "endpoint_classification",
            "producer_classification",
            "next_action",
            "recommended_patch",
        ],
    )
    _write_csv(
        review_dir / "manual_files_required_r4_8e.csv",
        manual_required_rows,
        [
            "priority",
            "source_family",
            "expected_input",
            "required_file_type",
            "accepted_filename_patterns",
            "required_columns",
            "target_dropzone_path",
            "target_output_path",
            "validation_command",
            "source_url_or_portal",
            "manual_export_steps",
            "producer_script",
            "required_env_vars",
            "retry_status",
            "failure_reason",
            "next_action",
            "manual_file_received",
            "review_status",
        ],
    )
    _write_csv(
        review_dir / "endpoint_followup_required_r4_8e.csv",
        endpoint_followup_rows,
        [
            "priority",
            "expected_input",
            "source_family",
            "producer_script",
            "source_url_or_portal",
            "failure_reason",
            "endpoint_classification",
            "next_action",
            "probe_attempted",
            "probe_ok",
            "probe_status_code",
            "probe_error",
            "review_status",
        ],
    )
    _write_csv(
        review_dir / "producer_patch_remaining_r4_8e.csv",
        producer_patch_remaining_rows,
        [
            "priority",
            "expected_input",
            "source_family",
            "producer_script",
            "retry_status",
            "failure_reason",
            "endpoint_classification",
            "producer_classification",
            "next_action",
            "recommended_patch",
            "review_status",
        ],
    )
    _write_csv(
        review_dir / "backfill_retry_order_r4_8e.csv",
        retry_order_r48e,
        [
            "retry_rank",
            "priority",
            "expected_input",
            "source_family",
            "endpoint_classification",
            "producer_classification",
            "next_action",
        ],
    )

    rebuild_status.update(
        {
            "r4_8e_generated_at": status_payload["generated_at"],
            "r4_8e_phase_type": status_payload["r4_8e_phase_type"],
            "r4_8e_gate_passed": status_payload["r4_8e_gate_passed"],
            "r4_8e_manual_fallback_sources": status_payload["r4_8e_manual_fallback_sources"],
            "r4_8e_endpoint_failures_reviewed": status_payload["r4_8e_endpoint_failures_reviewed"],
            "r4_8e_producer_failures_reviewed": status_payload["r4_8e_producer_failures_reviewed"],
            "r4_8e_manual_files_required": status_payload["r4_8e_manual_files_required"],
            "r4_8e_endpoint_followup_required": status_payload["r4_8e_endpoint_followup_required"],
            "r4_8e_producer_patch_remaining": status_payload["r4_8e_producer_patch_remaining"],
            "r4_8e_rows_ingested": status_payload["r4_8e_rows_ingested"],
            "r4_8e_production_inputs_staged": status_payload["r4_8e_production_inputs_staged"],
            "r4_8e_validated_source_manifests_written": status_payload[
                "r4_8e_validated_source_manifests_written"
            ],
            "r4_8e_forbidden_artifact_usage": status_payload["r4_8e_forbidden_artifact_usage"],
            "r4_8e_downloads_executed": status_payload["r4_8e_downloads_executed"],
            "r4_8e_outputs": status_payload["outputs"],
            "row_fabrication_policy": row_fabrication_policy,
            "phase_7_8_blocked": phase_7_8_blocked,
        }
    )
    _write_json(exports_dir / "rebuild_status.json", rebuild_status)

    return status_payload


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run R4.8E manual fallback package and endpoint/producer resolution planning"
    )
    parser.add_argument("--root", default=".", help="Project root")
    parser.add_argument(
        "--no-endpoint-probes",
        action="store_true",
        help="Disable lightweight endpoint probes and use failure text classification only.",
    )
    parser.add_argument(
        "--probe-timeout-seconds",
        type=int,
        default=6,
        help="Per-endpoint lightweight probe timeout.",
    )
    args = parser.parse_args()

    result = run_manual_fallback_endpoint_resolution(
        Path(args.root),
        enable_endpoint_probes=not bool(args.no_endpoint_probes),
        probe_timeout_seconds=max(1, int(args.probe_timeout_seconds)),
    )

    print(f"r4_8e_gate_passed: {result.get('r4_8e_gate_passed')}")
    print(f"r4_8e_manual_fallback_sources: {result.get('r4_8e_manual_fallback_sources')}")
    print(f"r4_8e_endpoint_failures_reviewed: {result.get('r4_8e_endpoint_failures_reviewed')}")
    print(f"r4_8e_producer_failures_reviewed: {result.get('r4_8e_producer_failures_reviewed')}")
    print(f"r4_8e_manual_files_required: {result.get('r4_8e_manual_files_required')}")
    print(f"r4_8e_endpoint_followup_required: {result.get('r4_8e_endpoint_followup_required')}")
    print(f"r4_8e_producer_patch_remaining: {result.get('r4_8e_producer_patch_remaining')}")
    print(f"r4_8e_rows_ingested: {result.get('r4_8e_rows_ingested')}")
    print(f"r4_8e_production_inputs_staged: {result.get('r4_8e_production_inputs_staged')}")
    print(
        "r4_8e_validated_source_manifests_written: "
        f"{result.get('r4_8e_validated_source_manifests_written')}"
    )
    print(f"r4_8e_forbidden_artifact_usage: {result.get('r4_8e_forbidden_artifact_usage')}")
    print(f"phase_7_8_blocked: {result.get('phase_7_8_blocked')}")
    print(json.dumps(result, indent=2))

    print("wrote: data/exports/manual_fallback_package_r4_8e.json")
    print("wrote: data/exports/manual_fallback_inventory_r4_8e.csv")
    print("wrote: data/exports/endpoint_resolution_report_r4_8e.csv")
    print("wrote: data/exports/producer_failure_resolution_report_r4_8e.csv")
    print("wrote: data/review_queue/manual_files_required_r4_8e.csv")
    print("wrote: data/review_queue/endpoint_followup_required_r4_8e.csv")
    print("wrote: data/review_queue/producer_patch_remaining_r4_8e.csv")
    print("wrote: data/review_queue/backfill_retry_order_r4_8e.csv")
    print("wrote: data/exports/rebuild_status.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
