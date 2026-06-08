"""R4.9G scoped unfreeze candidate validation and manifesting."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from contract_sweeper.pipeline.acquisition_package import (
    read_csv,
    read_json,
    safe_int,
    utc_now,
    write_csv,
    write_json,
)
from contract_sweeper.pipeline.delivered_source_validation import (
    contains_forbidden_token,
    relative_posix,
    resolve_abs,
    sha256,
    validate_candidate,
)

VALIDATED_MANIFEST_TYPE = "validated_source_manifest"
SCHEMA_VERSION = "r4_9g_scoped_unfreeze_v1"


def _truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in {"true", "1", "yes"}


def _checklist_by_expected(root: Path) -> dict[str, dict[str, str]]:
    rows = read_csv(root / "data" / "review_queue" / "source_delivery_checklist_r4_9e.csv")
    return {
        str(row.get("expected_input", "")).strip(): row
        for row in rows
        if str(row.get("expected_input", "")).strip()
    }


def _approved_target_match(
    *,
    candidate_relpath: str,
    expected_input: str,
    checklist: dict[str, str],
) -> bool:
    target_output = str(checklist.get("target_output_path", "")).strip()
    target_dropzone = str(checklist.get("target_dropzone_path", "")).strip()
    allowed_exact = {item for item in (expected_input, target_output, target_dropzone) if item}
    if candidate_relpath in allowed_exact:
        return True
    if target_dropzone and candidate_relpath.startswith(target_dropzone.rstrip("/") + "/"):
        return True
    return False


def _candidate_path(root: Path, row: dict[str, str]) -> Path:
    raw_path = str(row.get("candidate_path", "")).strip()
    if raw_path:
        return resolve_abs(root, raw_path)
    return resolve_abs(root, str(row.get("candidate_relpath", "")).strip())


def _manifest_relpath(index: int, candidate: Path) -> str:
    safe_name = candidate.name.replace("/", "_").replace("\\", "_")
    return f"data/manifests/r4_9g/{index:02d}_{safe_name}.manifest.json"


def _write_manifest(
    *,
    root: Path,
    generated_at: str,
    index: int,
    candidate: Path,
    candidate_relpath: str,
    candidate_row: dict[str, str],
    checklist: dict[str, str],
    row_count: int,
    digest: str,
) -> str:
    manifest_relpath = _manifest_relpath(index, candidate)
    manifest_path = root / manifest_relpath
    payload = {
        "generated_at": generated_at,
        "known_gaps": "partial scoped unfreeze only; unresolved sources remain blocked",
        "manifest_type": VALIDATED_MANIFEST_TYPE,
        "phase": "R4.9G_SCOPED_UNFREEZE",
        "producer_script": "scripts/run_scoped_unfreeze_retry_r49g.py",
        "row_count": row_count,
        "schema_version": SCHEMA_VERSION,
        "sha256": digest,
        "source_family": str(candidate_row.get("source_family", "")).strip(),
        "source_file": candidate_relpath,
        "source_system": str(candidate_row.get("source_family", "")).strip(),
        "target_output_path": str(checklist.get("target_output_path", "")).strip()
        or str(candidate_row.get("expected_input", "")).strip(),
        "unfreeze_condition": str(candidate_row.get("unfreeze_condition", "")).strip(),
        "validation_status": "validated",
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return manifest_relpath


def _blocked_rows_from_r49f(
    *,
    generated_at: str,
    still_missing_rows: list[dict[str, str]],
    rejected_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in still_missing_rows:
        rows.append(
            {
                "generated_at": generated_at,
                "expected_input": str(row.get("expected_input", "")).strip(),
                "source_family": str(row.get("source_family", "")).strip(),
                "blocker_class": str(row.get("blocker_class", "")).strip(),
                "target_dropzone_path": str(row.get("target_dropzone_path", "")).strip(),
                "target_output_path": str(row.get("target_output_path", "")).strip(),
                "blocker_reason": str(row.get("missing_reason", "")).strip()
                or "source_still_blocked",
                "next_action": str(row.get("next_action", "")).strip()
                or "await_external_source_delivery",
                "validation_command": str(row.get("validation_command", "")).strip(),
                "unfreeze_condition": str(row.get("unfreeze_condition", "")).strip(),
                "r4_9g_status": "still_blocked_from_r4_9f",
            }
        )

    for row in rejected_rows:
        rows.append(
            {
                "generated_at": generated_at,
                "expected_input": str(row.get("expected_input", "")).strip(),
                "source_family": str(row.get("source_family", "")).strip(),
                "blocker_class": str(row.get("blocker_class", "")).strip(),
                "target_dropzone_path": str(row.get("target_dropzone_path", "")).strip(),
                "target_output_path": str(row.get("target_output_path", "")).strip(),
                "blocker_reason": str(row.get("validation_reason", "")).strip()
                or "candidate_validation_failed",
                "next_action": "repair_candidate_delivery",
                "validation_command": str(row.get("validation_command", "")).strip(),
                "unfreeze_condition": str(row.get("unfreeze_condition", "")).strip(),
                "r4_9g_status": "r4_9g_candidate_rejected",
            }
        )
    return rows


def run_scoped_unfreeze_materialization(root: Path) -> dict[str, Any]:
    """Validate only R4.9F unfreeze candidates and write scoped manifests."""

    root = Path(root)
    exports_dir = root / "data" / "exports"
    review_dir = root / "data" / "review_queue"

    watch_status = read_json(exports_dir / "source_delivery_watch_status_r4_9f.json")
    rebuild_status = read_json(exports_dir / "rebuild_status.json")
    candidate_rows = read_csv(review_dir / "unfreeze_candidates_r4_9f.csv")
    still_missing_rows = read_csv(review_dir / "source_delivery_still_missing_r4_9f.csv")
    checklist_lookup = _checklist_by_expected(root)

    generated_at = utc_now()
    validation_rows: list[dict[str, Any]] = []
    validated_rows: list[dict[str, Any]] = []
    rejected_rows: list[dict[str, Any]] = []
    processed_expected_inputs: set[str] = set()
    forbidden_artifact_usage = False
    rows_available = 0

    for index, row in enumerate(candidate_rows, start=1):
        expected_input = str(row.get("expected_input", "")).strip()
        source_family = str(row.get("source_family", "")).strip()
        blocker_class = str(row.get("blocker_class", "")).strip()
        candidate = _candidate_path(root, row)
        candidate_relpath = relative_posix(root, candidate)
        candidate_filename = candidate.name
        checklist = checklist_lookup.get(expected_input, {})

        processed_expected_inputs.add(expected_input)
        validation_status = "rejected"
        validation_reason = ""
        manifest_path = ""
        candidate_sha = ""
        candidate_rows_count = 0
        target_match = False
        candidate_valid = False

        if contains_forbidden_token(str(candidate)) or contains_forbidden_token(expected_input):
            forbidden_artifact_usage = True
            validation_reason = "candidate_forbidden_artifact_path"
        elif not checklist:
            validation_reason = "candidate_not_listed_in_source_delivery_checklist"
        else:
            target_match = _approved_target_match(
                candidate_relpath=candidate_relpath,
                expected_input=expected_input,
                checklist=checklist,
            )
            if not target_match:
                validation_reason = "candidate_not_matching_approved_checklist_target"
            else:
                candidate_valid, details, fail_reason = validate_candidate(
                    root=root,
                    candidate=candidate,
                    expected_sha256=str(row.get("candidate_sha256", "")).strip(),
                    accepted_filename_patterns=str(
                        checklist.get("accepted_filename_patterns", "")
                    ).strip(),
                    required_columns=str(checklist.get("required_columns", "")).strip(),
                )
                candidate_sha = str(details.get("candidate_sha256", "")).strip() or sha256(
                    candidate
                )
                candidate_rows_count = safe_int(
                    details.get("candidate_row_count") or row.get("candidate_row_count")
                )
                validation_reason = (
                    "validated"
                    if candidate_valid
                    else (fail_reason or "candidate_validation_failed")
                )

        if candidate_valid:
            validation_status = "validated"
            rows_available += candidate_rows_count
            manifest_path = _write_manifest(
                root=root,
                generated_at=generated_at,
                index=index,
                candidate=candidate,
                candidate_relpath=candidate_relpath,
                candidate_row=row,
                checklist=checklist,
                row_count=candidate_rows_count,
                digest=candidate_sha,
            )
        elif not candidate_sha and candidate.exists() and candidate.is_file():
            candidate_sha = sha256(candidate)

        output_row = {
            "generated_at": generated_at,
            "expected_input": expected_input,
            "source_family": source_family,
            "blocker_class": blocker_class,
            "candidate_path": str(candidate),
            "candidate_relpath": candidate_relpath,
            "candidate_filename": candidate_filename,
            "target_dropzone_path": str(checklist.get("target_dropzone_path", "")).strip(),
            "target_output_path": str(checklist.get("target_output_path", "")).strip()
            or expected_input,
            "candidate_row_count": candidate_rows_count,
            "candidate_sha256": candidate_sha,
            "required_columns": str(checklist.get("required_columns", "")).strip(),
            "validation_command": str(
                checklist.get("validation_command") or row.get("validation_command", "")
            ).strip(),
            "unfreeze_condition": str(
                checklist.get("unfreeze_condition") or row.get("unfreeze_condition", "")
            ).strip(),
            "approved_target_match": target_match,
            "validation_status": validation_status,
            "validation_reason": validation_reason,
            "manifest_path": manifest_path,
            "output_status": "PARTIAL_DIAGNOSTIC" if candidate_valid else "BLOCKED_DIAGNOSTIC",
        }
        validation_rows.append(output_row)
        if candidate_valid:
            validated_rows.append(output_row)
        else:
            rejected_rows.append(output_row)

    blocked_rows = _blocked_rows_from_r49f(
        generated_at=generated_at,
        still_missing_rows=still_missing_rows,
        rejected_rows=rejected_rows,
    )

    candidates_loaded = len(candidate_rows)
    candidates_validated = len(validated_rows)
    candidates_rejected = len(rejected_rows)
    source_watch_unfreeze_candidates = safe_int(watch_status.get("r4_9f_unfreeze_candidates"))
    source_watch_still_missing = safe_int(watch_status.get("r4_9f_sources_still_missing"))
    only_candidate_rows_processed = len(processed_expected_inputs) == candidates_loaded
    every_candidate_accounted = candidates_loaded == candidates_validated + candidates_rejected
    unresolved_preserved = len(blocked_rows) >= len(still_missing_rows)
    if source_watch_still_missing:
        unresolved_preserved = (
            unresolved_preserved and len(blocked_rows) >= source_watch_still_missing
        )

    production_status = "NON_PRODUCTION_DIAGNOSTIC"
    phase_7_8_blocked = bool(rebuild_status.get("phase_7_8_blocked", True))
    downstream_phases_blocked = True
    downloads_executed = False
    endpoint_retries_executed = False
    production_inputs_staged = 0
    output_status = "PARTIAL_DIAGNOSTIC" if candidates_validated > 0 else "BLOCKED_DIAGNOSTIC"

    gate_passed = bool(
        candidates_loaded > 0
        and (source_watch_unfreeze_candidates in {0, candidates_loaded})
        and only_candidate_rows_processed
        and every_candidate_accounted
        and unresolved_preserved
        and not forbidden_artifact_usage
        and not downloads_executed
        and not endpoint_retries_executed
        and production_inputs_staged == 0
        and production_status == "NON_PRODUCTION_DIAGNOSTIC"
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
        "r4_9g_sources_still_blocked": len(blocked_rows),
        "r4_9g_partial_rebuild_attempted": False,
        "r4_9g_partial_rebuild_succeeded": False,
        "r4_9g_partial_rebuild_rows": 0,
        "r4_9g_unique_entities": 0,
        "r4_9g_source_lineage_coverage": 0.0,
        "r4_9g_output_status": output_status,
        "production_status": production_status,
        "r4_9g_downloads_executed": downloads_executed,
        "r4_9g_endpoint_retries_executed": endpoint_retries_executed,
        "r4_9g_production_inputs_staged": production_inputs_staged,
        "r4_9g_forbidden_artifact_usage": forbidden_artifact_usage,
        "phase_7_8_blocked": phase_7_8_blocked,
        "downstream_phases_blocked": downstream_phases_blocked,
        "r4_9g_only_candidate_rows_processed": only_candidate_rows_processed,
        "r4_9g_unresolved_sources_preserved": unresolved_preserved,
    }

    write_json(exports_dir / "scoped_unfreeze_status_r4_9g.json", status_payload)
    write_csv(
        exports_dir / "scoped_unfreeze_candidates_r4_9g.csv",
        validated_rows,
        [
            "generated_at",
            "expected_input",
            "source_family",
            "blocker_class",
            "candidate_path",
            "candidate_relpath",
            "candidate_filename",
            "target_dropzone_path",
            "target_output_path",
            "candidate_row_count",
            "candidate_sha256",
            "required_columns",
            "validation_command",
            "unfreeze_condition",
            "approved_target_match",
            "validation_status",
            "validation_reason",
            "manifest_path",
            "output_status",
        ],
    )
    write_csv(
        exports_dir / "scoped_unfreeze_validation_report_r4_9g.csv",
        validation_rows,
        [
            "generated_at",
            "expected_input",
            "source_family",
            "blocker_class",
            "candidate_path",
            "candidate_relpath",
            "candidate_filename",
            "target_dropzone_path",
            "target_output_path",
            "candidate_row_count",
            "candidate_sha256",
            "required_columns",
            "validation_command",
            "unfreeze_condition",
            "approved_target_match",
            "validation_status",
            "validation_reason",
            "manifest_path",
            "output_status",
        ],
    )
    write_csv(
        review_dir / "sources_still_blocked_r4_9g.csv",
        blocked_rows,
        [
            "generated_at",
            "expected_input",
            "source_family",
            "blocker_class",
            "target_dropzone_path",
            "target_output_path",
            "blocker_reason",
            "next_action",
            "validation_command",
            "unfreeze_condition",
            "r4_9g_status",
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
            "r4_9g_sources_still_blocked": len(blocked_rows),
            "r4_9g_partial_rebuild_attempted": False,
            "r4_9g_partial_rebuild_succeeded": False,
            "r4_9g_partial_rebuild_rows": 0,
            "r4_9g_unique_entities": 0,
            "r4_9g_source_lineage_coverage": 0.0,
            "r4_9g_output_status": output_status,
            "production_status": production_status,
            "r4_9g_downloads_executed": downloads_executed,
            "r4_9g_endpoint_retries_executed": endpoint_retries_executed,
            "r4_9g_production_inputs_staged": production_inputs_staged,
            "r4_9g_forbidden_artifact_usage": forbidden_artifact_usage,
            "phase_7_8_blocked": phase_7_8_blocked,
            "downstream_phases_blocked": downstream_phases_blocked,
        }
    )
    write_json(exports_dir / "rebuild_status.json", rebuild_status)

    return status_payload
