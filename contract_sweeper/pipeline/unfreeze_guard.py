"""Gate helpers for R4.9F source delivery watch and unfreeze guard."""

from __future__ import annotations

from typing import Any


def _as_bool(value: Any) -> bool:
    return str(value or "").strip().lower() in {"true", "1", "yes"}


def retry_suppression_preserved(
    *,
    retry_suppression_rows: list[dict[str, Any]],
    checklist_rows_checked: int,
    unfreeze_candidates: int,
) -> bool:
    suppressed = sum(
        1
        for row in retry_suppression_rows
        if str(row.get("suppression_status", "")).strip().lower() == "suppressed"
    )

    # Requirement: preserve suppression unless valid unfreeze candidates exist.
    if unfreeze_candidates > 0:
        return True
    return (
        suppressed >= checklist_rows_checked
        and len(retry_suppression_rows) >= checklist_rows_checked
    )


def downstream_blockers_preserved(
    downstream_blocker_rows: list[dict[str, Any]],
) -> bool:
    return bool(downstream_blocker_rows) and all(
        _as_bool(row.get("blocked")) for row in downstream_blocker_rows
    )


def evaluate_r49f_gate(
    *,
    checklist_rows_total: int,
    checklist_rows_checked: int,
    candidate_files_found: int,
    candidate_rows_evaluated: int,
    sources_still_missing: int,
    retry_suppression_ok: bool,
    downstream_blockers_ok: bool,
    downloads_executed: bool,
    rows_ingested: int,
    production_inputs_staged: int,
    forbidden_artifact_usage: bool,
    production_status: str,
    row_fabrication_policy: str,
    phase_7_8_blocked: bool,
) -> bool:
    found_candidates_accounted = candidate_rows_evaluated >= candidate_files_found
    missing_sources_queued = sources_still_missing >= 0

    return bool(
        checklist_rows_total == checklist_rows_checked
        and found_candidates_accounted
        and missing_sources_queued
        and retry_suppression_ok
        and downstream_blockers_ok
        and not downloads_executed
        and rows_ingested == 0
        and production_inputs_staged == 0
        and not forbidden_artifact_usage
        and production_status == "NON_PRODUCTION_DIAGNOSTIC"
        and row_fabrication_policy == "FORBIDDEN_NO_SYNTHETIC_ROWS"
        and phase_7_8_blocked
    )
