"""Credential and endpoint unblock planning for R4.8G."""

from __future__ import annotations

from typing import Any

from contract_sweeper.pipeline.acquisition_package import safe_int

SAFE_ENDPOINT_RETRY_COMMANDS = {
    "scripts/download_grants.py": "python scripts/download_grants.py --force",
    "scripts/download_fema.py": "python scripts/download_fema.py --force",
    "scripts/download_research.py": "python scripts/download_research.py --force",
    "scripts/download_cdbg_dr.py": "python scripts/download_cdbg_dr.py --force",
    "scripts/auto_download.py": "python scripts/auto_download.py --only usaspending --force",
}


def _infer_auth_status(
    *,
    endpoint_classification: str,
    failure_reason: str,
    producer_script: str,
) -> str:
    reason = str(failure_reason or "").lower()
    classification = str(endpoint_classification or "").lower()
    if any(token in reason for token in ("401", "403", "forbidden", "unauthorized", "token", "api key")):
        return "auth_or_permission_required"
    if classification == "endpoint_down":
        return "auth_unknown_check_required"
    if classification in {"endpoint_requires_auth", "endpoint_changed"}:
        return "auth_or_access_review_required"
    if producer_script == "scripts/auto_download.py":
        return "auth_and_rate_limit_check_required"
    return "auth_status_unknown_review_required"


def _recommended_endpoint_action(classification: str) -> str:
    normalized = str(classification or "").strip()
    return {
        "endpoint_down": "verify_endpoint_health_then_retry_with_backoff",
        "endpoint_changed": "update_endpoint_path_then_retry",
        "endpoint_requires_parameters": "adjust_request_parameters_then_retry",
        "endpoint_requires_auth": "configure_access_credentials_then_retry",
        "endpoint_deprecated": "migrate_to_supported_endpoint",
        "unknown_endpoint_failure": "manual_endpoint_triage",
    }.get(normalized, "manual_endpoint_triage")


def build_endpoint_and_credential_requests(
    endpoint_rows: list[dict[str, str]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    endpoint_request_rows: list[dict[str, Any]] = []
    credential_plan_rows: list[dict[str, Any]] = []
    credential_request_rows: list[dict[str, Any]] = []

    for row in sorted(endpoint_rows, key=lambda item: safe_int(item.get("priority"))):
        priority = safe_int(row.get("priority"))
        expected_input = str(row.get("expected_input", "")).strip()
        source_family = str(row.get("source_family", "")).strip()
        producer_script = str(row.get("producer_script", "")).strip()
        endpoint_classification = str(row.get("endpoint_classification", "")).strip()
        source_url_or_portal = str(row.get("source_url_or_portal", "")).strip()
        failure_reason = str(row.get("failure_reason", "")).strip()

        required_auth_status = _infer_auth_status(
            endpoint_classification=endpoint_classification,
            failure_reason=failure_reason,
            producer_script=producer_script,
        )
        recommended_action = _recommended_endpoint_action(endpoint_classification)
        safe_retry = SAFE_ENDPOINT_RETRY_COMMANDS.get(producer_script, "")

        endpoint_row = {
            "priority": priority,
            "source_family": source_family,
            "expected_input": expected_input,
            "endpoint_classification": endpoint_classification or "unknown_endpoint_failure",
            "source_url_or_portal": source_url_or_portal,
            "producer_script": producer_script,
            "required_credentials_or_auth_status": required_auth_status,
            "recommended_endpoint_action": recommended_action,
            "safe_retry_command_if_available": safe_retry,
            "reason_blocked": failure_reason or "endpoint retry unsuccessful",
        }
        endpoint_request_rows.append(endpoint_row)

        credential_row = dict(endpoint_row)
        credential_row["credential_request_reason"] = (
            "verify credentials, permissions, and rate-limit posture before next retry"
        )
        credential_plan_rows.append(credential_row)
        credential_request_rows.append(credential_row)

    return endpoint_request_rows, credential_plan_rows, credential_request_rows


def build_producer_patch_requests(
    producer_rows: list[dict[str, str]],
) -> list[dict[str, Any]]:
    request_rows: list[dict[str, Any]] = []
    for row in sorted(producer_rows, key=lambda item: safe_int(item.get("priority"))):
        priority = safe_int(row.get("priority"))
        failure_reason = str(row.get("failure_reason", "")).strip()
        retry_status = str(row.get("retry_status", "")).strip()
        producer_script = str(row.get("producer_script", "")).strip()

        manual_source_required = retry_status in {"failed_validation", "failed_no_data"}
        patch_safe_now = retry_status in {"failed_command", "no_deterministic_patch_available"}

        request_rows.append(
            {
                "priority": priority,
                "source_family": str(row.get("source_family", "")).strip(),
                "expected_input": str(row.get("expected_input", "")).strip(),
                "producer_script": producer_script,
                "failure_reason": failure_reason or "producer retry unsuccessful",
                "recommended_patch": (
                    "tighten request contract checks and add explicit endpoint diagnostics"
                    if patch_safe_now
                    else "hold patch until manual source or endpoint prerequisites are met"
                ),
                "patch_safe_now": patch_safe_now,
                "manual_source_required": manual_source_required,
            }
        )
    return request_rows
