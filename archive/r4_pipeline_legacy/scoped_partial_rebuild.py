"""R4.9G scoped partial diagnostic rebuild wrapper."""

from __future__ import annotations

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
from contract_sweeper.pipeline.delivered_source_validation import contains_forbidden_token


def _load_build_module() -> Any:
    from scripts import build_unified_master

    return build_unified_master


def _expected_input_list(build_module: Any) -> list[tuple[str, str]]:
    expected: list[tuple[str, str]] = [
        ("data/staging/processed/pr_contracts_master.csv", "contracts")
    ]
    for filename, dataset in getattr(build_module, "NEW_MASTERS", []):
        expected.append((f"data/staging/processed/{filename}", str(dataset)))
    for filename in getattr(build_module, "EXPANSION_FILES", []):
        expected.append((f"data/staging/expansion/{filename}", "usaspending_expansion"))
    return expected


def _safe_parquet_write(df: pd.DataFrame, path: Path) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(path, index=False)
        return True
    except Exception:
        return False


def _validated_candidate_lookup(rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    for row in rows:
        if str(row.get("validation_status", "")).strip() != "validated":
            continue
        expected_input = str(row.get("expected_input", "")).strip()
        if expected_input:
            out[expected_input] = row
    return out


def _build_input_map(
    *,
    root: Path,
    expected_inputs: list[tuple[str, str]],
    validated_lookup: dict[str, dict[str, str]],
) -> dict[str, dict[str, str]]:
    input_map: dict[str, dict[str, str]] = {}
    for expected_input, _dataset in expected_inputs:
        validation = validated_lookup.get(expected_input)
        if validation:
            candidate_path = str(validation.get("candidate_path", "")).strip()
            if not candidate_path:
                candidate_path = str(
                    (root / str(validation.get("candidate_relpath", "")).strip()).resolve()
                )
            input_map[expected_input] = {
                "mapped_rel": candidate_path,
                "mapping_mode": "r4_9g_scoped_candidate",
            }
        else:
            missing_rel = (
                "data/staging/processed/partial/r4_9g_missing/"
                + Path(expected_input).name
            )
            input_map[expected_input] = {
                "mapped_rel": missing_rel,
                "mapping_mode": "r4_9g_blocked_non_candidate",
            }
    return input_map


def _lineage_rows(
    *,
    root: Path,
    expected_inputs: list[tuple[str, str]],
    validated_lookup: dict[str, dict[str, str]],
    blocked_lookup: dict[str, dict[str, str]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for expected_input, source_dataset in expected_inputs:
        validation = validated_lookup.get(expected_input)
        blocked = blocked_lookup.get(expected_input, {})
        if validation:
            candidate_path = str(validation.get("candidate_path", "")).strip()
            candidate_relpath = str(validation.get("candidate_relpath", "")).strip()
            rows.append(
                {
                    "expected_input": expected_input,
                    "source_dataset": source_dataset,
                    "input_status": "validated_r4_9g_candidate",
                    "candidate_relpath": candidate_relpath,
                    "candidate_path": candidate_path,
                    "row_count": safe_int(validation.get("candidate_row_count")),
                    "sha256": str(validation.get("candidate_sha256", "")).strip(),
                    "source_family": str(validation.get("source_family", "")).strip(),
                    "source_manifest_path": str(validation.get("manifest_path", "")).strip(),
                    "lineage_path": candidate_relpath or candidate_path,
                    "mapping_mode": "r4_9g_scoped_candidate",
                    "reason": "validated candidate included in partial diagnostic rebuild",
                    "output_status": "PARTIAL_DIAGNOSTIC",
                }
            )
        else:
            rows.append(
                {
                    "expected_input": expected_input,
                    "source_dataset": source_dataset,
                    "input_status": "blocked_not_in_r4_9f_unfreeze_candidates",
                    "candidate_relpath": "",
                    "candidate_path": "",
                    "row_count": 0,
                    "sha256": "",
                    "source_family": str(blocked.get("source_family", "")).strip()
                    or source_dataset,
                    "source_manifest_path": "",
                    "lineage_path": "",
                    "mapping_mode": "r4_9g_blocked_non_candidate",
                    "reason": str(blocked.get("blocker_reason", "")).strip()
                    or "source not validated as R4.9F unfreeze candidate",
                    "output_status": "BLOCKED_DIAGNOSTIC",
                }
            )
    return rows


def _default_downstream_blockers(generated_at: str) -> list[dict[str, Any]]:
    phases = [
        "R4.9_PRODUCTION_MASTER_REBUILD",
        "R5_ENTITY_RESOLUTION",
        "R6_EXECUTION_CHAIN_REBUILD",
        "R7_FINANCIAL_INTEGRATION",
        "R8_GRAPH_REBUILD",
        "R9_RISK_ENGINE",
        "R10_FINAL_REPORTS",
    ]
    return [
        {
            "generated_at": generated_at,
            "phase_code": phase,
            "blocked": "True",
            "blocker_reason": "blocked by partial diagnostic source coverage",
            "unfreeze_condition": "complete required source delivery and validated coverage",
            "status": "blocked",
        }
        for phase in phases
    ]


def _downstream_blocker_rows(root: Path, generated_at: str) -> list[dict[str, Any]]:
    existing = read_csv(root / "data" / "review_queue" / "downstream_phase_blockers_r4_9f.csv")
    rows = existing or _default_downstream_blockers(generated_at)
    out: list[dict[str, Any]] = []
    for row in rows:
        out.append(
            {
                "generated_at": generated_at,
                "phase_code": str(row.get("phase_code", "")).strip(),
                "blocked": "True",
                "blocker_reason": str(row.get("blocker_reason", "")).strip()
                or "blocked by partial diagnostic source coverage",
                "unfreeze_condition": str(row.get("unfreeze_condition", "")).strip()
                or "complete required source delivery and validated coverage",
                "status": "blocked",
                "r4_9g_scope": "partial_diagnostic_only",
            }
        )
    return out


def run_scoped_partial_rebuild(
    root: Path,
    materialization_status: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Attempt a diagnostic rebuild using only validated R4.9G candidates."""

    root = Path(root)
    exports_dir = root / "data" / "exports"
    review_dir = root / "data" / "review_queue"
    partial_dir = root / "data" / "staging" / "processed" / "partial"

    generated_at = utc_now()
    rebuild_status = read_json(exports_dir / "rebuild_status.json")
    materialization_status = materialization_status or read_json(
        exports_dir / "scoped_unfreeze_status_r4_9g.json"
    )
    validation_rows = read_csv(exports_dir / "scoped_unfreeze_validation_report_r4_9g.csv")
    validated_rows = read_csv(exports_dir / "scoped_unfreeze_candidates_r4_9g.csv")
    blocked_rows = read_csv(review_dir / "sources_still_blocked_r4_9g.csv")
    watch_status = read_json(exports_dir / "source_delivery_watch_status_r4_9f.json")

    build_module = _load_build_module()
    expected_inputs = _expected_input_list(build_module)
    validated_lookup = _validated_candidate_lookup(validated_rows)
    blocked_lookup = {
        str(row.get("expected_input", "")).strip(): row
        for row in blocked_rows
        if str(row.get("expected_input", "")).strip()
    }

    candidates_loaded = safe_int(materialization_status.get("r4_9g_candidates_loaded"))
    candidates_validated = safe_int(materialization_status.get("r4_9g_candidates_validated"))
    candidates_rejected = safe_int(materialization_status.get("r4_9g_candidates_rejected"))
    rows_available = safe_int(materialization_status.get("r4_9g_rows_available"))
    sources_still_blocked = len(blocked_rows)
    expected_sources_still_blocked = safe_int(watch_status.get("r4_9f_sources_still_missing"))

    forbidden_artifact_usage = bool(
        materialization_status.get("r4_9g_forbidden_artifact_usage", False)
    )
    forbidden_artifact_usage = bool(
        forbidden_artifact_usage
        or any(contains_forbidden_token(str(row.get("candidate_path", ""))) for row in validation_rows)
        or any(contains_forbidden_token(str(row.get("expected_input", ""))) for row in blocked_rows)
    )

    partial_rebuild_attempted = False
    partial_rebuild_succeeded = False
    partial_rebuild_rows = 0
    unique_entities = 0
    source_lineage_coverage = 0.0
    output_status = "BLOCKED_DIAGNOSTIC"
    rebuild_error = ""
    parquet_written = False

    partial_master_csv = partial_dir / "contracts_master_partial_diagnostic_r4_9g.csv"
    partial_master_parquet = partial_dir / "contracts_master_partial_diagnostic_r4_9g.parquet"
    partial_entities_csv = partial_dir / "entities_partial_diagnostic_r4_9g.csv"

    if candidates_validated > 0 and not forbidden_artifact_usage:
        partial_rebuild_attempted = True
        try:
            input_map = _build_input_map(
                root=root,
                expected_inputs=expected_inputs,
                validated_lookup=validated_lookup,
            )
            with tempfile.TemporaryDirectory(prefix="r49g_partial_workspace_") as tmpdir:
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
                    df_master["diagnostic_status"] = "PARTIAL_DIAGNOSTIC"
                    df_master["diagnostic_phase"] = "R4.9G_SCOPED_UNFREEZE"
                    partial_rebuild_rows = int(len(df_master))
                    if "recipient_name_normalized" in df_master.columns:
                        unique_entities = int(
                            df_master["recipient_name_normalized"]
                            .fillna("")
                            .replace("", pd.NA)
                            .dropna()
                            .nunique()
                        )
                    source_lineage_coverage = float(
                        summary.get("source_lineage_coverage", 0.0) or 0.0
                    )
                    partial_dir.mkdir(parents=True, exist_ok=True)
                    df_master.to_csv(partial_master_csv, index=False, encoding="utf-8")
                    parquet_written = _safe_parquet_write(df_master, partial_master_parquet)

                if workspace_entities.exists():
                    df_entities = pd.read_csv(workspace_entities, dtype=str, low_memory=False)
                    df_entities["diagnostic_status"] = "PARTIAL_DIAGNOSTIC"
                    df_entities["diagnostic_phase"] = "R4.9G_SCOPED_UNFREEZE"
                    df_entities.to_csv(partial_entities_csv, index=False, encoding="utf-8")
                    if unique_entities <= 0:
                        unique_entities = int(len(df_entities))

                partial_rebuild_succeeded = partial_rebuild_rows > 0
                output_status = (
                    "PARTIAL_DIAGNOSTIC" if partial_rebuild_succeeded else "BLOCKED_DIAGNOSTIC"
                )
                if not partial_rebuild_succeeded:
                    rebuild_error = "partial diagnostic rebuild produced zero rows"
        except Exception as exc:  # pragma: no cover - defensive fail-closed path
            rebuild_error = str(exc)
            output_status = "BLOCKED_DIAGNOSTIC"
    else:
        rebuild_error = (
            "forbidden_artifact_usage_detected"
            if forbidden_artifact_usage
            else "no_validated_r4_9g_candidates"
        )

    lineage_rows = _lineage_rows(
        root=root,
        expected_inputs=expected_inputs,
        validated_lookup=validated_lookup,
        blocked_lookup=blocked_lookup,
    )
    downstream_rows = _downstream_blocker_rows(root, generated_at)
    downstream_phases_blocked = bool(downstream_rows) and all(
        str(row.get("blocked", "")).strip().lower() == "true" for row in downstream_rows
    )

    production_status = "NON_PRODUCTION_DIAGNOSTIC"
    downloads_executed = False
    endpoint_retries_executed = False
    production_inputs_staged = 0
    phase_7_8_blocked = bool(rebuild_status.get("phase_7_8_blocked", True))
    candidates_accounted = candidates_loaded == candidates_validated + candidates_rejected
    only_candidates_processed = bool(
        materialization_status.get("r4_9g_only_candidate_rows_processed", False)
    )
    unresolved_preserved = bool(
        materialization_status.get("r4_9g_unresolved_sources_preserved", False)
    )
    if expected_sources_still_blocked:
        unresolved_preserved = unresolved_preserved and sources_still_blocked >= expected_sources_still_blocked

    diagnostic_output_valid = output_status in {"PARTIAL_DIAGNOSTIC", "BLOCKED_DIAGNOSTIC"}

    gate_passed = bool(
        candidates_loaded > 0
        and only_candidates_processed
        and candidates_accounted
        and unresolved_preserved
        and diagnostic_output_valid
        and production_status == "NON_PRODUCTION_DIAGNOSTIC"
        and not downloads_executed
        and not endpoint_retries_executed
        and production_inputs_staged == 0
        and not forbidden_artifact_usage
        and phase_7_8_blocked
        and downstream_phases_blocked
    )

    status_payload = {
        "generated_at": generated_at,
        "r4_9g_gate_passed": gate_passed,
        "r4_9g_candidates_loaded": candidates_loaded,
        "r4_9g_candidates_validated": candidates_validated,
        "r4_9g_candidates_rejected": candidates_rejected,
        "r4_9g_rows_available": rows_available,
        "r4_9g_sources_still_blocked": sources_still_blocked,
        "r4_9g_partial_rebuild_attempted": partial_rebuild_attempted,
        "r4_9g_partial_rebuild_succeeded": partial_rebuild_succeeded,
        "r4_9g_partial_rebuild_rows": partial_rebuild_rows,
        "r4_9g_unique_entities": unique_entities,
        "r4_9g_source_lineage_coverage": round(float(source_lineage_coverage), 4),
        "r4_9g_output_status": output_status,
        "production_status": production_status,
        "r4_9g_downloads_executed": downloads_executed,
        "r4_9g_endpoint_retries_executed": endpoint_retries_executed,
        "r4_9g_production_inputs_staged": production_inputs_staged,
        "r4_9g_forbidden_artifact_usage": forbidden_artifact_usage,
        "phase_7_8_blocked": phase_7_8_blocked,
        "downstream_phases_blocked": downstream_phases_blocked,
        "r4_9g_rebuild_error": rebuild_error,
        "r4_9g_parquet_written": parquet_written,
        "r4_9g_outputs": {
            "partial_master_csv": str(partial_master_csv),
            "partial_master_parquet": str(partial_master_parquet),
            "partial_entities_csv": str(partial_entities_csv),
            "status": "data/exports/scoped_partial_rebuild_status_r4_9g.json",
            "lineage": "data/exports/scoped_partial_rebuild_lineage_r4_9g.csv",
            "downstream_blockers": "data/review_queue/downstream_phase_blockers_r4_9g.csv",
        },
    }

    write_json(exports_dir / "scoped_partial_rebuild_status_r4_9g.json", status_payload)
    write_csv(
        exports_dir / "scoped_partial_rebuild_lineage_r4_9g.csv",
        lineage_rows,
        [
            "expected_input",
            "source_dataset",
            "input_status",
            "candidate_relpath",
            "candidate_path",
            "row_count",
            "sha256",
            "source_family",
            "source_manifest_path",
            "lineage_path",
            "mapping_mode",
            "reason",
            "output_status",
        ],
    )
    write_csv(
        review_dir / "downstream_phase_blockers_r4_9g.csv",
        downstream_rows,
        [
            "generated_at",
            "phase_code",
            "blocked",
            "blocker_reason",
            "unfreeze_condition",
            "status",
            "r4_9g_scope",
        ],
    )

    rebuild_status.update(
        {
            "r4_9g_generated_at": generated_at,
            "r4_9g_gate_passed": gate_passed,
            "r4_9g_candidates_loaded": candidates_loaded,
            "r4_9g_candidates_validated": candidates_validated,
            "r4_9g_candidates_rejected": candidates_rejected,
            "r4_9g_rows_available": rows_available,
            "r4_9g_sources_still_blocked": sources_still_blocked,
            "r4_9g_partial_rebuild_attempted": partial_rebuild_attempted,
            "r4_9g_partial_rebuild_succeeded": partial_rebuild_succeeded,
            "r4_9g_partial_rebuild_rows": partial_rebuild_rows,
            "r4_9g_unique_entities": unique_entities,
            "r4_9g_source_lineage_coverage": round(float(source_lineage_coverage), 4),
            "r4_9g_output_status": output_status,
            "production_status": production_status,
            "r4_9g_downloads_executed": downloads_executed,
            "r4_9g_endpoint_retries_executed": endpoint_retries_executed,
            "r4_9g_production_inputs_staged": production_inputs_staged,
            "r4_9g_forbidden_artifact_usage": forbidden_artifact_usage,
            "phase_7_8_blocked": phase_7_8_blocked,
            "downstream_phases_blocked": downstream_phases_blocked,
            "r4_9g_outputs": status_payload["r4_9g_outputs"],
        }
    )
    write_json(exports_dir / "rebuild_status.json", rebuild_status)

    return status_payload
