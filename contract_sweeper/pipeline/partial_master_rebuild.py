"""R4.9A partial diagnostic master rebuild orchestration."""

from __future__ import annotations

import inspect
import tempfile
from pathlib import Path
from typing import Any

import pandas as pd

from contract_sweeper.pipeline.acquisition_package import (
    read_csv,
    read_json,
    safe_int,
    utc_now,
    write_csv,
    write_json,
)
from contract_sweeper.pipeline.partial_rebuild_gate import (
    derive_output_status,
    evaluate_partial_gate,
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


def _contains_forbidden_token(text: str) -> bool:
    lowered = str(text or "").lower()
    return any(token in lowered for token in FORBIDDEN_ARTIFACT_TOKENS)


def _load_build_module() -> Any:
    from scripts import build_unified_master  # local import for testability

    return build_unified_master


def _detect_partial_support(build_module: Any) -> tuple[bool, str]:
    run_fn = getattr(build_module, "run", None)
    if run_fn is None:
        return False, "build_unified_master.run missing"

    sig = inspect.signature(run_fn)
    params = sig.parameters
    required = {"input_map", "require_all_inputs", "fail_on_forbidden"}
    missing = sorted(required - set(params.keys()))
    if missing:
        return False, "missing run() parameters: " + ", ".join(missing)

    return True, "run() supports mapped partial diagnostic execution"


def _expected_input_list(build_module: Any) -> list[tuple[str, str]]:
    expected: list[tuple[str, str]] = [("data/staging/processed/pr_contracts_master.csv", "contracts")]

    for filename, dataset in getattr(build_module, "NEW_MASTERS", []):
        expected.append((f"data/staging/processed/{filename}", str(dataset)))

    for filename in getattr(build_module, "EXPANSION_FILES", []):
        expected.append((f"data/staging/expansion/{filename}", "usaspending_expansion"))

    return expected


def _validated_manifest_rows(root: Path, rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        target = str(row.get("target_output_path", "")).strip()
        if not target:
            continue
        if _contains_forbidden_token(target):
            continue

        abs_path = root / target
        if not abs_path.exists() or not abs_path.is_file():
            continue

        row_count = safe_int(row.get("row_count"))
        sha = str(row.get("sha256", "")).strip()
        if row_count <= 0 or not sha:
            continue

        out.append(
            {
                "source_system": str(row.get("source_system", "")).strip(),
                "source_file": str(row.get("source_file", "")).strip(),
                "target_output_path": target,
                "row_count": row_count,
                "sha256": sha,
                "generated_at": str(row.get("generated_at", "")).strip(),
                "producer_script": str(row.get("producer_script", "")).strip(),
                "validation_status": str(row.get("validation_status", "")).strip(),
                "known_gaps": str(row.get("known_gaps", "")).strip(),
                "schema_version": str(row.get("schema_version", "")).strip(),
                "manifest_type": str(row.get("manifest_type", "")).strip(),
                "manifest_path": str(row.get("manifest_path", "")).strip(),
            }
        )
    return out


def _build_input_rows(
    *,
    expected_inputs: list[tuple[str, str]],
    validated_rows: list[dict[str, Any]],
    missing_manual_rows: list[dict[str, str]],
    input_map: dict[str, dict[str, str]],
) -> list[dict[str, Any]]:
    validated_by_target = {
        str(row.get("target_output_path", "")).strip(): row for row in validated_rows
    }
    missing_by_expected = {
        str(row.get("expected_input", "")).strip(): row for row in missing_manual_rows
    }

    rows: list[dict[str, Any]] = []
    for expected_input, source_dataset in expected_inputs:
        mapping = input_map.get(expected_input, {})
        mapped_rel = str(mapping.get("mapped_rel", expected_input))
        mapping_mode = str(mapping.get("mapping_mode", "exact"))
        validation = validated_by_target.get(expected_input)
        missing = missing_by_expected.get(expected_input)

        status = "missing"
        row_count = 0
        sha256 = ""
        source_system = source_dataset
        source_file = ""
        lineage_path = mapped_rel
        reason = "not validated"

        if validation:
            status = "validated_available"
            row_count = safe_int(validation.get("row_count"))
            sha256 = str(validation.get("sha256", ""))
            source_system = str(validation.get("source_system", source_dataset))
            source_file = str(validation.get("source_file", ""))
            lineage_path = str(validation.get("target_output_path", expected_input))
            reason = "validated manifest input"
        elif missing:
            status = "missing_manual_blocker"
            reason = str(missing.get("failure_reason", "manual file still required"))

        rows.append(
            {
                "expected_input": expected_input,
                "source_dataset": source_dataset,
                "mapped_input_path": mapped_rel,
                "mapping_mode": mapping_mode,
                "input_status": status,
                "row_count": row_count,
                "sha256": sha256,
                "source_system": source_system,
                "source_file": source_file,
                "lineage_path": lineage_path,
                "reason": reason,
            }
        )

    return rows


def _build_gap_report(
    *,
    expected_inputs: list[tuple[str, str]],
    input_rows: list[dict[str, Any]],
    missing_manual_rows: list[dict[str, str]],
    external_blocker_count: int,
) -> list[dict[str, Any]]:
    status_by_input = {
        str(row.get("expected_input", "")).strip(): str(row.get("input_status", "")).strip()
        for row in input_rows
    }
    manual_missing = {
        str(row.get("expected_input", "")).strip(): row for row in missing_manual_rows
    }

    gap_rows: list[dict[str, Any]] = []
    for expected_input, source_dataset in expected_inputs:
        status = status_by_input.get(expected_input, "missing")
        is_gap = status != "validated_available"
        manual_row = manual_missing.get(expected_input)

        gap_rows.append(
            {
                "expected_input": expected_input,
                "source_dataset": source_dataset,
                "gap_status": "missing" if is_gap else "present",
                "manual_blocker": bool(manual_row),
                "manual_blocker_reason": str(
                    (manual_row or {}).get("failure_reason", "")
                ).strip(),
                "external_blocker_impact": external_blocker_count if is_gap else 0,
            }
        )

    return gap_rows


def _build_lineage_report(input_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in input_rows:
        out.append(
            {
                "expected_input": str(row.get("expected_input", "")).strip(),
                "source_system": str(row.get("source_system", "")).strip(),
                "source_file": str(row.get("source_file", "")).strip(),
                "lineage_path": str(row.get("lineage_path", "")).strip(),
                "mapping_mode": str(row.get("mapping_mode", "")).strip(),
                "input_status": str(row.get("input_status", "")).strip(),
                "row_count": safe_int(row.get("row_count")),
                "sha256": str(row.get("sha256", "")).strip(),
            }
        )
    return out


def _build_blocker_rows(
    *,
    missing_manual_rows: list[dict[str, str]],
    endpoint_blocked_rows: list[dict[str, str]],
    producer_blocked_rows: list[dict[str, str]],
    support_reason: str,
    rebuild_error: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    for row in missing_manual_rows:
        rows.append(
            {
                "blocker_type": "manual_missing",
                "priority": safe_int(row.get("priority")),
                "source_family": str(row.get("source_family", "")).strip(),
                "expected_input": str(row.get("expected_input", "")).strip(),
                "reason": str(row.get("failure_reason", "manual file still required")).strip(),
                "next_action": "manual_file_delivery",
            }
        )

    for row in endpoint_blocked_rows:
        rows.append(
            {
                "blocker_type": "endpoint_blocked",
                "priority": safe_int(row.get("priority")),
                "source_family": str(row.get("source_family", "")).strip(),
                "expected_input": str(row.get("expected_input", "")).strip(),
                "reason": str(row.get("failure_reason", "endpoint blocked")).strip(),
                "next_action": "endpoint_resolution",
            }
        )

    for row in producer_blocked_rows:
        rows.append(
            {
                "blocker_type": "producer_blocked",
                "priority": safe_int(row.get("priority")),
                "source_family": str(row.get("source_family", "")).strip(),
                "expected_input": str(row.get("expected_input", "")).strip(),
                "reason": str(row.get("failure_reason", "producer blocked")).strip(),
                "next_action": "producer_retry",
            }
        )

    if support_reason:
        rows.append(
            {
                "blocker_type": "partial_mode_support",
                "priority": 0,
                "source_family": "system",
                "expected_input": "build_unified_master.run",
                "reason": support_reason,
                "next_action": "continue_diagnostic" if "supports" in support_reason else "block",
            }
        )

    if rebuild_error:
        rows.append(
            {
                "blocker_type": "rebuild_error",
                "priority": 0,
                "source_family": "system",
                "expected_input": "partial_diagnostic_rebuild",
                "reason": rebuild_error,
                "next_action": "debug_wrapper",
            }
        )

    rows.sort(
        key=lambda row: (
            safe_int(row.get("priority")),
            str(row.get("blocker_type", "")),
            str(row.get("expected_input", "")),
        )
    )
    return rows


def _safe_parquet_write(df: pd.DataFrame, path: Path) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(path, index=False)
        return True
    except Exception:
        return False


def run_partial_master_rebuild(root: Path) -> dict[str, Any]:
    root = Path(root)
    exports_dir = root / "data" / "exports"
    review_dir = root / "data" / "review_queue"
    partial_dir = root / "data" / "staging" / "processed" / "partial"

    # Required inputs
    _ = read_json(exports_dir / "final_source_recovery_status_r4_8i.json")
    _ = read_csv(exports_dir / "final_source_recovery_results_r4_8i.csv")
    manifest_rows_raw = read_csv(exports_dir / "validated_source_manifest_inventory_r4_8i.csv")
    external_blocker_package = read_json(exports_dir / "external_acquisition_blocker_package_r4_8i.json")
    missing_manual_rows = read_csv(review_dir / "manual_files_still_required_r4_8i.csv")
    endpoint_blocked_rows = read_csv(review_dir / "endpoints_still_blocked_r4_8i.csv")
    producer_blocked_rows = read_csv(review_dir / "producers_still_blocked_r4_8i.csv")
    _ = read_csv(review_dir / "backfill_retry_order_r4_8i.csv")

    rebuild_status = read_json(exports_dir / "rebuild_status.json")

    build_module = _load_build_module()
    partial_supported, support_reason = _detect_partial_support(build_module)

    expected_inputs = _expected_input_list(build_module)
    validated_rows = _validated_manifest_rows(root, manifest_rows_raw)
    validated_lookup = {
        str(row.get("target_output_path", "")).strip(): row for row in validated_rows
    }

    input_map: dict[str, dict[str, str]] = {}
    for expected_input, _dataset in expected_inputs:
        if expected_input in validated_lookup:
            input_map[expected_input] = {
                "mapped_rel": str((root / expected_input).resolve()),
                "mapping_mode": "r4_9a_validated",
            }
        else:
            input_map[expected_input] = {
                "mapped_rel": f"data/staging/processed/partial/r4_9a_missing/{Path(expected_input).name}",
                "mapping_mode": "r4_9a_missing",
            }

    forbidden_artifact_usage = bool(
        any(_contains_forbidden_token(str(row.get("target_output_path", ""))) for row in validated_rows)
        or any(_contains_forbidden_token(str(row.get("expected_input", ""))) for row in missing_manual_rows)
        or any(_contains_forbidden_token(str(row.get("expected_input", ""))) for row in endpoint_blocked_rows)
        or any(_contains_forbidden_token(str(row.get("expected_input", ""))) for row in producer_blocked_rows)
    )

    external_blocker_count = safe_int(external_blocker_package.get("external_blocker_count"))
    if external_blocker_count <= 0:
        external_blocker_count = len(external_blocker_package.get("blockers", []))

    rebuild_attempted = False
    rebuild_succeeded = False
    rebuild_error = ""
    output_rows = 0
    unique_entities = 0
    source_lineage_coverage = 0.0

    partial_master_csv = partial_dir / "contracts_master_partial_diagnostic.csv"
    partial_master_parquet = partial_dir / "contracts_master_partial_diagnostic.parquet"
    partial_entities_csv = partial_dir / "entities_partial_diagnostic.csv"

    if partial_supported and not forbidden_artifact_usage and len(validated_rows) > 0:
        rebuild_attempted = True
        try:
            with tempfile.TemporaryDirectory(prefix="r49a_partial_workspace_") as tmpdir:
                workspace_root = Path(tmpdir)
                summary = build_module.run(
                    root=workspace_root,
                    input_map=input_map,
                    require_all_inputs=False,
                    fail_on_forbidden=True,
                )

                workspace_processed = workspace_root / "data" / "staging" / "processed"
                workspace_master = workspace_processed / "pr_all_awards_master.csv"
                workspace_entities = workspace_processed / "entity_master.csv"

                if workspace_master.exists():
                    df_master = pd.read_csv(workspace_master, dtype=str, low_memory=False)
                    output_rows = int(len(df_master))
                    if "recipient_name_normalized" in df_master.columns:
                        unique_entities = int(
                            df_master["recipient_name_normalized"].fillna("").replace("", pd.NA).dropna().nunique()
                        )
                    source_lineage_coverage = float(summary.get("source_lineage_coverage", 0.0) or 0.0)

                    partial_dir.mkdir(parents=True, exist_ok=True)
                    df_master.to_csv(partial_master_csv, index=False, encoding="utf-8")
                    _safe_parquet_write(df_master, partial_master_parquet)

                if workspace_entities.exists():
                    df_entities = pd.read_csv(workspace_entities, dtype=str, low_memory=False)
                    df_entities.to_csv(partial_entities_csv, index=False, encoding="utf-8")
                    if unique_entities <= 0:
                        unique_entities = int(len(df_entities))

                rebuild_succeeded = output_rows > 0
                if not rebuild_succeeded:
                    rebuild_error = "partial wrapper executed but produced zero output rows"
        except Exception as exc:  # pragma: no cover - defensive
            rebuild_error = str(exc)
            rebuild_succeeded = False
    else:
        if not partial_supported:
            rebuild_error = support_reason
        elif forbidden_artifact_usage:
            rebuild_error = "forbidden artifact usage detected"
        else:
            rebuild_error = "no validated inputs available for partial diagnostic rebuild"

    output_status = derive_output_status(rebuild_succeeded)
    production_status = "NON_PRODUCTION_DIAGNOSTIC"
    row_fabrication_policy = str(
        rebuild_status.get("row_fabrication_policy") or "FORBIDDEN_NO_SYNTHETIC_ROWS"
    )
    phase_7_8_blocked = bool(rebuild_status.get("phase_7_8_blocked", True))

    input_rows = _build_input_rows(
        expected_inputs=expected_inputs,
        validated_rows=validated_rows,
        missing_manual_rows=missing_manual_rows,
        input_map=input_map,
    )
    gap_rows = _build_gap_report(
        expected_inputs=expected_inputs,
        input_rows=input_rows,
        missing_manual_rows=missing_manual_rows,
        external_blocker_count=external_blocker_count,
    )
    lineage_rows = _build_lineage_report(input_rows)

    missing_inputs_rows = [
        {
            "priority": safe_int(row.get("priority")),
            "source_family": str(row.get("source_family", "")).strip(),
            "expected_input": str(row.get("expected_input", "")).strip(),
            "target_output_path": str(row.get("target_output_path", "")).strip(),
            "failure_reason": str(row.get("failure_reason", "")).strip() or "manual file still required",
            "review_status": str(row.get("review_status", "")).strip() or "pending_manual_file",
        }
        for row in missing_manual_rows
    ]

    blocker_rows = _build_blocker_rows(
        missing_manual_rows=missing_manual_rows,
        endpoint_blocked_rows=endpoint_blocked_rows,
        producer_blocked_rows=producer_blocked_rows,
        support_reason=support_reason,
        rebuild_error=rebuild_error if not rebuild_succeeded else "",
    )

    accounted_inputs = len(input_rows) == len(expected_inputs) and len(missing_inputs_rows) == len(missing_manual_rows)
    rebuild_state_valid = bool(rebuild_succeeded or (not rebuild_succeeded and rebuild_error))

    gate_passed = evaluate_partial_gate(
        inputs_accounted=accounted_inputs,
        rebuild_state_valid=rebuild_state_valid,
        forbidden_artifact_usage=forbidden_artifact_usage,
        row_fabrication_policy=row_fabrication_policy,
        production_status=production_status,
        phase_7_8_blocked=phase_7_8_blocked,
    )

    status_payload = {
        "generated_at": utc_now(),
        "r4_9a_phase_type": "PARTIAL_DIAGNOSTIC_MASTER_REBUILD",
        "r4_9a_gate_passed": gate_passed,
        "r4_9a_validated_inputs_available": len(validated_rows),
        "r4_9a_missing_inputs": len(missing_inputs_rows),
        "r4_9a_external_blockers": external_blocker_count,
        "r4_9a_rebuild_attempted": rebuild_attempted,
        "r4_9a_rebuild_succeeded": rebuild_succeeded,
        "r4_9a_output_rows": output_rows,
        "r4_9a_unique_entities": unique_entities,
        "r4_9a_source_lineage_coverage": round(float(source_lineage_coverage), 4),
        "r4_9a_forbidden_artifact_usage": forbidden_artifact_usage,
        "r4_9a_output_status": output_status,
        "production_status": production_status,
        "row_fabrication_policy": row_fabrication_policy,
        "phase_7_8_blocked": phase_7_8_blocked,
        "inputs": {
            "final_source_recovery_status_r4_8i": "data/exports/final_source_recovery_status_r4_8i.json",
            "final_source_recovery_results_r4_8i": "data/exports/final_source_recovery_results_r4_8i.csv",
            "validated_source_manifest_inventory_r4_8i": "data/exports/validated_source_manifest_inventory_r4_8i.csv",
            "external_acquisition_blocker_package_r4_8i": "data/exports/external_acquisition_blocker_package_r4_8i.json",
            "manual_files_still_required_r4_8i": "data/review_queue/manual_files_still_required_r4_8i.csv",
            "endpoints_still_blocked_r4_8i": "data/review_queue/endpoints_still_blocked_r4_8i.csv",
            "producers_still_blocked_r4_8i": "data/review_queue/producers_still_blocked_r4_8i.csv",
            "backfill_retry_order_r4_8i": "data/review_queue/backfill_retry_order_r4_8i.csv",
        },
        "outputs": {
            "status": "data/exports/partial_master_rebuild_status_r4_9a.json",
            "inputs_report": "data/exports/partial_master_rebuild_inputs_r4_9a.csv",
            "gap_report": "data/exports/partial_master_rebuild_gap_report_r4_9a.csv",
            "lineage_report": "data/exports/partial_master_rebuild_lineage_report_r4_9a.csv",
            "missing_inputs_queue": "data/review_queue/partial_master_missing_inputs_r4_9a.csv",
            "blockers_queue": "data/review_queue/partial_master_blockers_r4_9a.csv",
            "partial_master_csv": str(partial_master_csv),
            "partial_master_parquet": str(partial_master_parquet),
            "partial_entities_csv": str(partial_entities_csv),
        },
    }

    write_json(exports_dir / "partial_master_rebuild_status_r4_9a.json", status_payload)

    write_csv(
        exports_dir / "partial_master_rebuild_inputs_r4_9a.csv",
        input_rows,
        [
            "expected_input",
            "source_dataset",
            "mapped_input_path",
            "mapping_mode",
            "input_status",
            "row_count",
            "sha256",
            "source_system",
            "source_file",
            "lineage_path",
            "reason",
        ],
    )

    write_csv(
        exports_dir / "partial_master_rebuild_gap_report_r4_9a.csv",
        gap_rows,
        [
            "expected_input",
            "source_dataset",
            "gap_status",
            "manual_blocker",
            "manual_blocker_reason",
            "external_blocker_impact",
        ],
    )

    write_csv(
        exports_dir / "partial_master_rebuild_lineage_report_r4_9a.csv",
        lineage_rows,
        [
            "expected_input",
            "source_system",
            "source_file",
            "lineage_path",
            "mapping_mode",
            "input_status",
            "row_count",
            "sha256",
        ],
    )

    write_csv(
        review_dir / "partial_master_missing_inputs_r4_9a.csv",
        missing_inputs_rows,
        [
            "priority",
            "source_family",
            "expected_input",
            "target_output_path",
            "failure_reason",
            "review_status",
        ],
    )

    write_csv(
        review_dir / "partial_master_blockers_r4_9a.csv",
        blocker_rows,
        [
            "blocker_type",
            "priority",
            "source_family",
            "expected_input",
            "reason",
            "next_action",
        ],
    )

    rebuild_status.update(
        {
            "r4_9a_generated_at": status_payload["generated_at"],
            "r4_9a_phase_type": status_payload["r4_9a_phase_type"],
            "r4_9a_gate_passed": gate_passed,
            "r4_9a_validated_inputs_available": len(validated_rows),
            "r4_9a_missing_inputs": len(missing_inputs_rows),
            "r4_9a_external_blockers": external_blocker_count,
            "r4_9a_rebuild_attempted": rebuild_attempted,
            "r4_9a_rebuild_succeeded": rebuild_succeeded,
            "r4_9a_output_rows": output_rows,
            "r4_9a_unique_entities": unique_entities,
            "r4_9a_source_lineage_coverage": round(float(source_lineage_coverage), 4),
            "r4_9a_forbidden_artifact_usage": forbidden_artifact_usage,
            "r4_9a_output_status": output_status,
            "production_status": production_status,
            "r4_9a_outputs": status_payload["outputs"],
            "row_fabrication_policy": row_fabrication_policy,
            "phase_7_8_blocked": phase_7_8_blocked,
        }
    )
    write_json(exports_dir / "rebuild_status.json", rebuild_status)

    return status_payload
