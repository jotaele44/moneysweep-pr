"""R4.9H2 raw USAspending mapping feasibility review."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from contract_sweeper.pipeline.acquisition_package import (
    read_csv,
    read_json,
    safe_int,
    split_pipe,
    utc_now,
    write_csv,
    write_json,
)

LINEAGE_DERIVABLE_COLUMNS = {
    "source_file",
    "source_system",
    "source_dataset",
    "source_record_id",
    "source_lineage_path",
    "source_lineage_mode",
}

CRITICAL_IDENTITY_COLUMNS = {
    "award_id",
    "recipient_name",
    "awarding_agency",
    "awarding_sub_agency",
}

MONETARY_DATE_COLUMNS = {
    "award_date",
    "fiscal_year",
    "obligated_amount",
}

EXPLICIT_PR_SCOPE_COLUMNS = {
    "pop_state",
    "place_of_performance_state_code",
    "place_of_performance_state",
    "recipient_state_code",
    "recipient_state",
}

PR_SCOPE_PATH_TOKENS = (
    "puerto_rico",
    "puerto-rico",
    "_pr_",
    "_pr.",
    "/pr_",
    "-pr-",
)


def _columns_set(row: dict[str, str]) -> set[str]:
    return {column.lower() for column in split_pipe(row.get("raw_columns"))}


def _raw_path_has_pr_scope(raw_display_path: str) -> bool:
    lowered = str(raw_display_path or "").lower()
    return any(token in lowered for token in PR_SCOPE_PATH_TOKENS)


def _pop_state_bucket(row: dict[str, str]) -> tuple[str, str]:
    columns = _columns_set(row)
    raw_path = str(row.get("raw_display_path", "")).strip()
    if columns & EXPLICIT_PR_SCOPE_COLUMNS:
        return (
            "filterable_from_raw_data",
            "explicit place or recipient state columns can support PR filtering",
        )
    if _raw_path_has_pr_scope(raw_path):
        return (
            "deterministically_derivable",
            "raw file path indicates Puerto Rico scope",
        )
    if "is_pr_vendor" in columns:
        return (
            "cannot_infer_safely",
            "is_pr_vendor exists but does not prove every record has Puerto Rico place scope",
        )
    return (
        "cannot_infer_safely",
        "no explicit PR place field, PR-scoped filename, or verified filter metadata",
    )


def _classify_missing_column(row: dict[str, str], column: str) -> tuple[str, str]:
    normalized = column.strip().lower()
    columns = _columns_set(row)

    if normalized == "pop_state":
        return _pop_state_bucket(row)
    if normalized in columns:
        return (
            "directly_mappable",
            "raw column exists with the required target name",
        )
    if normalized in LINEAGE_DERIVABLE_COLUMNS:
        return (
            "deterministically_derivable",
            "lineage and source metadata can be derived from raw path and row position",
        )
    if normalized in MONETARY_DATE_COLUMNS:
        return (
            "requires_external_source",
            "monetary/date fields require explicit raw columns",
        )
    if normalized in CRITICAL_IDENTITY_COLUMNS:
        return (
            "requires_external_source",
            "award identity and recipient/agency fields require explicit raw columns",
        )
    return (
        "cannot_infer_safely",
        "no deterministic rule available for this required field",
    )


def _append_bucket(buckets: dict[str, list[str]], bucket: str, column: str) -> None:
    buckets.setdefault(bucket, []).append(column)


def classify_feasibility(row: dict[str, str], generated_at: str) -> dict[str, Any]:
    missing_columns = split_pipe(row.get("missing_columns"))
    buckets: dict[str, list[str]] = {
        "directly_mappable": [],
        "deterministically_derivable": [],
        "filterable_from_raw_data": [],
        "requires_external_source": [],
        "cannot_infer_safely": [],
    }
    notes: list[str] = []

    for column in missing_columns:
        bucket, note = _classify_missing_column(row, column)
        _append_bucket(buckets, bucket, column)
        notes.append(f"{column}:{note}")

    blocking = buckets["requires_external_source"] + buckets["cannot_infer_safely"]
    feasibility_status = "transform_candidate" if not blocking else "transform_reject"
    feasibility_reason = (
        "all missing columns are directly mappable, derivable, or filterable"
        if feasibility_status == "transform_candidate"
        else "missing columns require external data or unsafe inference"
    )

    return {
        "generated_at": generated_at,
        "expected_input": str(row.get("expected_input", "")).strip(),
        "source_family": str(row.get("source_family", "")).strip(),
        "blocker_class": str(row.get("blocker_class", "")).strip(),
        "target_output_path": str(row.get("target_output_path", "")).strip(),
        "raw_display_path": str(row.get("raw_display_path", "")).strip(),
        "raw_member_path": str(row.get("raw_member_path", "")).strip(),
        "raw_row_count": safe_int(row.get("raw_row_count")),
        "raw_sha256": str(row.get("raw_sha256", "")).strip(),
        "likely_source_type": str(row.get("likely_source_type", "")).strip(),
        "missing_columns": "|".join(missing_columns),
        "directly_mappable_columns": "|".join(buckets["directly_mappable"]),
        "deterministically_derivable_columns": "|".join(
            buckets["deterministically_derivable"]
        ),
        "filterable_from_raw_data_columns": "|".join(buckets["filterable_from_raw_data"]),
        "requires_external_source_columns": "|".join(buckets["requires_external_source"]),
        "cannot_infer_safely_columns": "|".join(buckets["cannot_infer_safely"]),
        "preexisting_mapped_columns": str(row.get("mapped_columns", "")).strip(),
        "feasibility_status": feasibility_status,
        "feasibility_reason": feasibility_reason,
        "classification_notes": "|".join(notes),
        "transform_phase_allowed": "False",
    }


def _merge_still_blocked_rows(
    *,
    generated_at: str,
    still_blocked_rows: list[dict[str, str]],
    transform_candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    candidate_targets = {
        str(row.get("expected_input", "")).strip()
        for row in transform_candidates
        if str(row.get("expected_input", "")).strip()
    }
    out: list[dict[str, Any]] = []
    for row in still_blocked_rows:
        expected_input = str(row.get("expected_input", "")).strip()
        potential = expected_input in candidate_targets
        out.append(
            {
                "generated_at": generated_at,
                "expected_input": expected_input,
                "source_family": str(row.get("source_family", "")).strip(),
                "blocker_class": str(row.get("blocker_class", "")).strip(),
                "target_dropzone_path": str(row.get("target_dropzone_path", "")).strip(),
                "target_output_path": str(row.get("target_output_path", "")).strip(),
                "blocker_reason": (
                    "pending_explicit_raw_transform_phase"
                    if potential
                    else str(row.get("blocker_reason", "")).strip()
                    or "external_source_or_access_still_required"
                ),
                "next_action": (
                    "review_and_authorize_explicit_transform_phase"
                    if potential
                    else "external_source_delivery_required"
                ),
                "validation_command": str(row.get("validation_command", "")).strip(),
                "unfreeze_condition": str(row.get("unfreeze_condition", "")).strip(),
                "r4_9h2_status": (
                    "potential_transform_candidate_but_still_blocked"
                    if potential
                    else "still_external_only"
                ),
            }
        )
    return out


def run_raw_usaspending_mapping_feasibility(root: Path) -> dict[str, Any]:
    root = Path(root)
    exports_dir = root / "data" / "exports"
    review_dir = root / "data" / "review_queue"

    generated_at = utc_now()
    rejected_rows = read_csv(review_dir / "raw_usaspending_rejected_candidates_r4_9h.csv")
    _ = read_csv(exports_dir / "raw_usaspending_candidate_matches_r4_9h.csv")
    _ = read_csv(exports_dir / "raw_usaspending_validation_report_r4_9h.csv")
    still_blocked_r4_9h = read_csv(review_dir / "sources_still_blocked_r4_9h.csv")
    _ = read_csv(review_dir / "source_delivery_checklist_r4_9e.csv")
    rebuild_status = read_json(exports_dir / "rebuild_status.json")

    matrix_rows = [classify_feasibility(row, generated_at) for row in rejected_rows]
    transform_candidates = [
        row for row in matrix_rows if row["feasibility_status"] == "transform_candidate"
    ]
    transform_rejects = [
        row for row in matrix_rows if row["feasibility_status"] != "transform_candidate"
    ]
    potentially_unblockable_targets = {
        str(row.get("expected_input", "")).strip()
        for row in transform_candidates
        if str(row.get("expected_input", "")).strip()
    }
    all_blocked_targets = {
        str(row.get("expected_input", "")).strip()
        for row in still_blocked_r4_9h
        if str(row.get("expected_input", "")).strip()
    }
    still_external_only_targets = all_blocked_targets - potentially_unblockable_targets
    still_blocked_h2 = _merge_still_blocked_rows(
        generated_at=generated_at,
        still_blocked_rows=still_blocked_r4_9h,
        transform_candidates=transform_candidates,
    )

    downloads_executed = False
    rows_ingested = 0
    production_inputs_staged = 0
    unfreeze_candidates_created = 0
    production_status = "NON_PRODUCTION_DIAGNOSTIC"
    phase_7_8_blocked = bool(rebuild_status.get("phase_7_8_blocked", True))
    downstream_phases_blocked = bool(rebuild_status.get("downstream_phases_blocked", True))

    all_reviewed = len(matrix_rows) == len(rejected_rows)
    every_classified = all(
        str(row.get("feasibility_status", "")).strip()
        and str(row.get("feasibility_reason", "")).strip()
        for row in matrix_rows
    )
    gate_passed = bool(
        all_reviewed
        and every_classified
        and not downloads_executed
        and rows_ingested == 0
        and production_inputs_staged == 0
        and unfreeze_candidates_created == 0
        and production_status == "NON_PRODUCTION_DIAGNOSTIC"
        and phase_7_8_blocked
        and downstream_phases_blocked
    )

    status_payload = {
        "generated_at": generated_at,
        "r4_9h2_gate_passed": gate_passed,
        "rejected_candidates_reviewed": len(matrix_rows),
        "transform_candidates": len(transform_candidates),
        "transform_rejects": len(transform_rejects),
        "targets_potentially_unblockable": len(potentially_unblockable_targets),
        "targets_still_external_only": len(still_external_only_targets),
        "downloads_executed": downloads_executed,
        "rows_ingested": rows_ingested,
        "production_inputs_staged": production_inputs_staged,
        "unfreeze_candidates_created": unfreeze_candidates_created,
        "production_status": production_status,
        "phase_7_8_blocked": phase_7_8_blocked,
        "downstream_phases_blocked": downstream_phases_blocked,
    }

    fieldnames = [
        "generated_at",
        "expected_input",
        "source_family",
        "blocker_class",
        "target_output_path",
        "raw_display_path",
        "raw_member_path",
        "raw_row_count",
        "raw_sha256",
        "likely_source_type",
        "missing_columns",
        "directly_mappable_columns",
        "deterministically_derivable_columns",
        "filterable_from_raw_data_columns",
        "requires_external_source_columns",
        "cannot_infer_safely_columns",
        "preexisting_mapped_columns",
        "feasibility_status",
        "feasibility_reason",
        "classification_notes",
        "transform_phase_allowed",
    ]
    write_json(
        exports_dir / "raw_usaspending_mapping_feasibility_status_r4_9h2.json",
        status_payload,
    )
    write_csv(
        exports_dir / "raw_usaspending_mapping_feasibility_matrix_r4_9h2.csv",
        matrix_rows,
        fieldnames,
    )
    write_csv(
        review_dir / "raw_usaspending_transform_candidates_r4_9h2.csv",
        transform_candidates,
        fieldnames,
    )
    write_csv(
        review_dir / "raw_usaspending_transform_rejects_r4_9h2.csv",
        transform_rejects,
        fieldnames,
    )
    write_csv(
        review_dir / "sources_still_blocked_r4_9h2.csv",
        still_blocked_h2,
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
            "r4_9h2_status",
        ],
    )

    rebuild_status.update(
        {
            "r4_9h2_generated_at": generated_at,
            "r4_9h2_gate_passed": gate_passed,
            "r4_9h2_rejected_candidates_reviewed": len(matrix_rows),
            "r4_9h2_transform_candidates": len(transform_candidates),
            "r4_9h2_transform_rejects": len(transform_rejects),
            "r4_9h2_targets_potentially_unblockable": len(potentially_unblockable_targets),
            "r4_9h2_targets_still_external_only": len(still_external_only_targets),
            "r4_9h2_downloads_executed": downloads_executed,
            "r4_9h2_rows_ingested": rows_ingested,
            "r4_9h2_production_inputs_staged": production_inputs_staged,
            "r4_9h2_unfreeze_candidates_created": unfreeze_candidates_created,
            "production_status": production_status,
            "phase_7_8_blocked": phase_7_8_blocked,
            "downstream_phases_blocked": downstream_phases_blocked,
        }
    )
    write_json(exports_dir / "rebuild_status.json", rebuild_status)

    return status_payload
