"""Endpoint failure classification and light probe support for R4.8E."""

from __future__ import annotations

import socket
import urllib.error
import urllib.request
from typing import Any


def _classify_from_text(reason: str) -> str:
    text = str(reason or "").lower()
    if any(
        token in text for token in ("401", "403", "unauthorized", "forbidden", "api key", "token")
    ):
        return "endpoint_requires_auth"
    if any(token in text for token in ("deprecated", "sunset", "410", "gone")):
        return "endpoint_deprecated"
    if any(token in text for token in ("301", "302", "307", "308", "moved", "redirect")):
        return "endpoint_changed"
    if any(token in text for token in ("parameter", "query", "invalid request", "400", "422")):
        return "endpoint_requires_parameters"
    if any(
        token in text
        for token in (
            "timeout",
            "timed out",
            "connection",
            "dns",
            "service unavailable",
            "502",
            "503",
            "504",
            "endpoint unavailable",
            "max retries exceeded",
            "name or service not known",
            "temporary failure",
        )
    ):
        return "endpoint_down"
    return "unknown_endpoint_failure"


def _probe_endpoint(url: str, timeout_seconds: int) -> tuple[bool, int, str]:
    if not url.startswith(("http://", "https://")):
        return False, 0, "unsupported_or_missing_url"

    methods = ("HEAD", "GET")
    last_error = ""
    for method in methods:
        request = urllib.request.Request(url, method=method)
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                return True, int(getattr(response, "status", 200)), ""
        except urllib.error.HTTPError as exc:
            return True, int(exc.code), str(exc.reason or "")
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, socket.timeout):
                return False, 0, "timeout"
            last_error = str(exc.reason or exc)
        except TimeoutError:
            return False, 0, "timeout"
        except Exception as exc:  # pragma: no cover - defensive
            last_error = str(exc)
    return False, 0, last_error or "probe_failed"


def _classify_from_probe(probe_ok: bool, status_code: int, probe_error: str) -> str:
    if status_code in {401, 403}:
        return "endpoint_requires_auth"
    if status_code in {404, 410}:
        return "endpoint_deprecated"
    if status_code in {301, 302, 307, 308}:
        return "endpoint_changed"
    if status_code in {400, 422}:
        return "endpoint_requires_parameters"
    if status_code >= 500:
        return "endpoint_down"
    if probe_ok and 200 <= status_code < 300:
        # Endpoint is reachable but producer still failed; this usually points
        # to request parameters, filters, or payload contract mismatch.
        return "endpoint_requires_parameters"

    lowered = str(probe_error or "").lower()
    if any(
        token in lowered for token in ("timeout", "refused", "name or service", "temporary failure")
    ):
        return "endpoint_down"
    return "unknown_endpoint_failure"


def _next_action(classification: str) -> str:
    return {
        "endpoint_down": "retry_endpoint_after_backoff",
        "endpoint_changed": "update_producer_endpoint_url",
        "endpoint_requires_parameters": "patch_query_parameters_and_retry",
        "endpoint_requires_auth": "configure_credentials_or_access",
        "endpoint_deprecated": "migrate_to_supported_endpoint",
        "unknown_endpoint_failure": "manual_endpoint_triage",
    }.get(classification, "manual_endpoint_triage")


def review_endpoint_failures(
    *,
    endpoint_rows: list[dict[str, str]],
    runner_manifest_by_input: dict[str, dict[str, str]],
    probe_timeout_seconds: int = 6,
    enable_probes: bool = True,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    report_rows: list[dict[str, Any]] = []
    followup_rows: list[dict[str, Any]] = []

    def _priority(row: dict[str, str]) -> int:
        try:
            return int(float(str(row.get("priority", "0") or "0")))
        except ValueError:
            return 0

    for row in sorted(endpoint_rows, key=_priority):
        expected_input = str(row.get("expected_input", "")).strip()
        runner_row = runner_manifest_by_input.get(expected_input, {})
        failure_reason = str(row.get("failure_reason") or row.get("reason") or "").strip()
        source_url_or_portal = str(runner_row.get("source_url_or_portal", "")).strip()

        probe_attempted = bool(
            enable_probes and source_url_or_portal.startswith(("http://", "https://"))
        )
        probe_ok = False
        probe_status_code = 0
        probe_error = ""
        if probe_attempted:
            probe_ok, probe_status_code, probe_error = _probe_endpoint(
                source_url_or_portal,
                timeout_seconds=max(1, int(probe_timeout_seconds)),
            )

        text_classification = _classify_from_text(failure_reason)
        if text_classification == "unknown_endpoint_failure" and probe_attempted:
            classification = _classify_from_probe(probe_ok, probe_status_code, probe_error)
        else:
            classification = text_classification

        report_row = {
            "priority": row.get("priority", ""),
            "expected_input": expected_input,
            "source_family": row.get("source_family", ""),
            "producer_script": runner_row.get("likely_producer_script", ""),
            "source_url_or_portal": source_url_or_portal,
            "failure_reason": failure_reason,
            "endpoint_classification": classification,
            "next_action": _next_action(classification),
            "probe_attempted": str(probe_attempted),
            "probe_ok": str(probe_ok),
            "probe_status_code": str(probe_status_code) if probe_status_code else "",
            "probe_error": str(probe_error or ""),
        }
        report_rows.append(report_row)

        followup_row = dict(report_row)
        followup_row["review_status"] = "pending_followup"
        followup_rows.append(followup_row)

    return report_rows, followup_rows
