from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

DEFAULT_TIMEOUT_MINUTES = 20
MAX_TIMEOUT_MINUTES = 360
TIMEOUT_OVERRIDES = {
    "grants_gov": 360,
    "rdc_demandas_civiles": 180,
}


def execution_timeout_minutes(
    source_id: str,
    *,
    overrides: Mapping[str, int] = TIMEOUT_OVERRIDES,
) -> int:
    timeout = overrides.get(source_id, DEFAULT_TIMEOUT_MINUTES)
    if isinstance(timeout, bool) or not isinstance(timeout, int):
        raise TypeError(f"timeout for {source_id!r} must be an integer")
    if timeout < 1 or timeout > MAX_TIMEOUT_MINUTES:
        raise ValueError(
            f"timeout for {source_id!r} must be between 1 and {MAX_TIMEOUT_MINUTES} minutes"
        )
    return timeout


def build_execution_plan(
    status_rows: Iterable[Mapping[str, Any]],
    recovery_rows: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    status_by_id: dict[str, Mapping[str, Any]] = {}
    for row in status_rows:
        source_id = str(row.get("source_id", "")).strip()
        if not source_id:
            raise ValueError("source status row has blank source_id")
        if source_id in status_by_id:
            raise ValueError(f"duplicate source status row: {source_id}")
        status_by_id[source_id] = row

    keyless_by_id: dict[str, dict[str, Any]] = {}
    credential_by_id: dict[str, dict[str, str]] = {}
    seen_recovery_ids: set[str] = set()
    for row in recovery_rows:
        source_id = str(row.get("source_id", "")).strip()
        if not source_id:
            raise ValueError("source recovery row has blank source_id")
        if source_id in seen_recovery_ids:
            raise ValueError(f"duplicate source recovery row: {source_id}")
        seen_recovery_ids.add(source_id)
        if str(row.get("automatable", "")).strip().lower() != "true":
            continue

        source = status_by_id.get(source_id)
        if source is None:
            raise ValueError(f"automatable source missing status row: {source_id}")
        authentication = str(source.get("authentication", "")).strip()
        if authentication == "none":
            keyless_by_id[source_id] = {
                "source": source_id,
                "timeout_minutes": execution_timeout_minutes(source_id),
            }
        else:
            credential_by_id[source_id] = {
                "source_id": source_id,
                "authentication": authentication,
                "producer_script": str(source.get("producer_script", "")).strip(),
            }

    return {
        "keyless": [keyless_by_id[source_id] for source_id in sorted(keyless_by_id)],
        "credential_gated": [credential_by_id[source_id] for source_id in sorted(credential_by_id)],
    }
