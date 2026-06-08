"""Producer-failure classification for R4.8E."""

from __future__ import annotations

from typing import Any


def _classify_producer_failure(
    *,
    retry_status: str,
    failure_reason: str,
    producer_script: str,
    endpoint_classification: str,
) -> str:
    reason = str(failure_reason or "").lower()
    status = str(retry_status or "").lower()
    script = str(producer_script or "")

    if endpoint_classification:
        return "requires_endpoint_review"

    if "no normalized files found" in reason:
        return "requires_manual_source"

    if status == "failed_no_data":
        return "requires_manual_source"

    if any(
        token in reason for token in ("timeout", "connection", "ssl", "dns", "service unavailable")
    ):
        return "requires_endpoint_review"

    if status == "failed_command":
        if script.startswith("scripts/download_"):
            return "patchable_now"
        return "leave_blocked_with_reason"

    if status.startswith("not_retried_"):
        return "requires_endpoint_review"

    return "leave_blocked_with_reason"


def _recommended_patch(classification: str, producer_script: str) -> str:
    if classification == "patchable_now":
        return (
            "Add explicit endpoint diagnostics, preserve nonzero failure exits, "
            "and ensure retry mode is opt-in with EMPTY-or-nonfatal tagging."
        )
    if classification == "requires_endpoint_review":
        return (
            "Hold producer patch until endpoint health/auth/parameter contract is reviewed; "
            "then retest with bounded retries."
        )
    if classification == "requires_manual_source":
        return (
            "Manual source file is required to unblock this producer output; "
            "keep producer in blocked state until manual import validates."
        )
    return "Leave blocked with explicit reason and retain fallback queue."


def _next_action(classification: str) -> str:
    return {
        "patchable_now": "patch_producer_script",
        "requires_endpoint_review": "endpoint_review_then_retry",
        "requires_manual_source": "require_manual_file",
        "leave_blocked_with_reason": "leave_blocked_with_reason",
    }.get(classification, "leave_blocked_with_reason")


def review_producer_failures(
    *,
    producer_rows: list[dict[str, str]],
    retry_results_by_input: dict[str, dict[str, str]],
    endpoint_report_by_input: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    report_rows: list[dict[str, Any]] = []
    patch_remaining_rows: list[dict[str, Any]] = []

    def _priority(row: dict[str, str]) -> int:
        try:
            return int(float(str(row.get("priority", "0") or "0")))
        except ValueError:
            return 0

    for row in sorted(producer_rows, key=_priority):
        expected_input = str(row.get("expected_input", "")).strip()
        retry_row = retry_results_by_input.get(expected_input, {})
        retry_status = str(retry_row.get("retry_status") or row.get("retry_status") or "").strip()
        failure_reason = str(
            retry_row.get("failure_reason") or row.get("failure_reason") or row.get("reason") or ""
        ).strip()
        producer_script = str(
            row.get("producer_script") or retry_row.get("producer_script") or ""
        ).strip()
        endpoint_classification = str(
            endpoint_report_by_input.get(expected_input, {}).get("endpoint_classification", "")
        ).strip()

        classification = _classify_producer_failure(
            retry_status=retry_status,
            failure_reason=failure_reason,
            producer_script=producer_script,
            endpoint_classification=endpoint_classification,
        )

        report_row = {
            "priority": row.get("priority", ""),
            "expected_input": expected_input,
            "source_family": row.get("source_family", ""),
            "producer_script": producer_script,
            "retry_status": retry_status,
            "failure_reason": failure_reason,
            "endpoint_classification": endpoint_classification,
            "producer_classification": classification,
            "next_action": _next_action(classification),
            "recommended_patch": _recommended_patch(classification, producer_script),
        }
        report_rows.append(report_row)

        if classification in {
            "patchable_now",
            "requires_endpoint_review",
            "leave_blocked_with_reason",
        }:
            queue_row = dict(report_row)
            queue_row["review_status"] = "pending"
            patch_remaining_rows.append(queue_row)

    return report_rows, patch_remaining_rows
