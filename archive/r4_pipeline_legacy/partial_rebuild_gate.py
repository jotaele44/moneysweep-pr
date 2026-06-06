"""Gate evaluation helpers for R4.9A partial diagnostic rebuild."""

from __future__ import annotations


def derive_output_status(rebuild_succeeded: bool) -> str:
    return "PARTIAL_DIAGNOSTIC" if rebuild_succeeded else "BLOCKED_DIAGNOSTIC"


def evaluate_partial_gate(
    *,
    inputs_accounted: bool,
    rebuild_state_valid: bool,
    forbidden_artifact_usage: bool,
    row_fabrication_policy: str,
    production_status: str,
    phase_7_8_blocked: bool,
) -> bool:
    return bool(
        inputs_accounted
        and rebuild_state_valid
        and not forbidden_artifact_usage
        and row_fabrication_policy == "FORBIDDEN_NO_SYNTHETIC_ROWS"
        and production_status == "NON_PRODUCTION_DIAGNOSTIC"
        and phase_7_8_blocked
    )
