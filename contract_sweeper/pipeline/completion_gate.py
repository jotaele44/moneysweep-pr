"""Classification and gate helpers for R4.9D external blocker freeze."""

from __future__ import annotations

from typing import Any


BLOCKER_MANUAL = "manual_file_required"
BLOCKER_PHYSICAL = "physical_validated_file_missing"
BLOCKER_ENDPOINT = "endpoint_delivery_blocked"
BLOCKER_PRODUCER = "producer_delivery_blocked"
BLOCKER_UNKNOWN = "unknown_external_blocker"

VALID_BLOCKER_CLASSES = {
    BLOCKER_MANUAL,
    BLOCKER_PHYSICAL,
    BLOCKER_ENDPOINT,
    BLOCKER_PRODUCER,
    BLOCKER_UNKNOWN,
}


def classify_blocker(row: dict[str, Any]) -> str:
    request_type = str(row.get("request_type", "")).strip().lower()
    reason = str(row.get("blocker_reason", "")).strip().lower()
    next_action = str(row.get("next_action", "")).strip().lower()
    source_family = str(row.get("source_family", "")).strip().lower()

    if request_type == "manual_file_delivery":
        return BLOCKER_MANUAL
    if request_type == "validated_manifest_delivery":
        return BLOCKER_PHYSICAL

    endpoint_hints = ("endpoint", "auth", "credential", "api", "portal_access")
    producer_hints = ("producer", "script", "parser", "normalizer", "mapper")

    if any(hint in reason for hint in endpoint_hints) or any(
        hint in next_action for hint in endpoint_hints
    ):
        return BLOCKER_ENDPOINT

    if any(hint in reason for hint in producer_hints) or any(
        hint in next_action for hint in producer_hints
    ):
        return BLOCKER_PRODUCER

    if "endpoint" in source_family:
        return BLOCKER_ENDPOINT
    if "producer" in source_family:
        return BLOCKER_PRODUCER

    return BLOCKER_UNKNOWN


def unfreeze_condition(
    blocker_class: str,
    *,
    expected_input: str,
    target_output_path: str,
    target_dropzone_path: str,
) -> str:
    if blocker_class == BLOCKER_MANUAL:
        return (
            "Provide the required manual source file under "
            f"{target_dropzone_path or target_output_path}, validate schema/rows, and stage to {target_output_path}."
        )
    if blocker_class == BLOCKER_PHYSICAL:
        return (
            "Deliver the physical validated source file for "
            f"{expected_input} with matching manifest-compatible hash and nonzero rows."
        )
    if blocker_class == BLOCKER_ENDPOINT:
        return "Restore endpoint access/credential path, deliver source file, and re-run delivery validation."
    if blocker_class == BLOCKER_PRODUCER:
        return "Patch producer delivery path, regenerate source file, and pass source validation with manifest linkage."
    return "Provide externally delivered source file and supporting provenance needed to validate and stage the expected input."


def evaluate_completion_gate(
    *,
    blockers_total: int,
    blockers_frozen: int,
    all_classified: bool,
    all_have_unfreeze_condition: bool,
    retry_suppression_count: int,
    downstream_blockers_count: int,
    downloads_executed: bool,
    rows_ingested: int,
    production_inputs_staged: int,
    forbidden_artifact_usage: bool,
    production_status: str,
    row_fabrication_policy: str,
    phase_7_8_blocked: bool,
) -> bool:
    return bool(
        blockers_total == blockers_frozen
        and all_classified
        and all_have_unfreeze_condition
        and retry_suppression_count > 0
        and downstream_blockers_count > 0
        and not downloads_executed
        and rows_ingested == 0
        and production_inputs_staged == 0
        and not forbidden_artifact_usage
        and production_status == "NON_PRODUCTION_DIAGNOSTIC"
        and row_fabrication_policy == "FORBIDDEN_NO_SYNTHETIC_ROWS"
        and phase_7_8_blocked
    )
