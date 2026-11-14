from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import date
from typing import Any

DEFAULT_TIMEOUT_MINUTES = 20
MAX_TIMEOUT_MINUTES = 360
GRANTS_SOURCE_ID = "grants_gov"
GRANTS_START_FY = 2000
GRANTS_SHARD_FY_SPAN = 7
GRANTS_SHARD_TIMEOUT_MINUTES = 360
GRANTS_PASSES = (
    "grants_pop",
    "grants_recipient",
    "direct_recipient",
    "loans_recipient",
)
TIMEOUT_OVERRIDES = {
    GRANTS_SOURCE_ID: MAX_TIMEOUT_MINUTES,
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


def current_fiscal_year(today: date | None = None) -> int:
    today = today or date.today()
    return today.year + 1 if today.month >= 10 else today.year


def build_grants_shard_plan(
    *,
    start_fy: int = GRANTS_START_FY,
    end_fy: int | None = None,
    span: int = GRANTS_SHARD_FY_SPAN,
) -> list[dict[str, Any]]:
    end_fy = current_fiscal_year() if end_fy is None else end_fy
    if isinstance(start_fy, bool) or not isinstance(start_fy, int):
        raise TypeError("grants start fiscal year must be an integer")
    if isinstance(end_fy, bool) or not isinstance(end_fy, int):
        raise TypeError("grants end fiscal year must be an integer")
    if isinstance(span, bool) or not isinstance(span, int):
        raise TypeError("grants shard span must be an integer")
    if start_fy < 1900 or end_fy < start_fy:
        raise ValueError("invalid grants fiscal-year range")
    if span < 1:
        raise ValueError("grants shard span must be positive")

    shards: list[dict[str, Any]] = []
    for pass_name in GRANTS_PASSES:
        for shard_start in range(start_fy, end_fy + 1, span):
            shard_end = min(shard_start + span - 1, end_fy)
            shards.append(
                {
                    "shard_id": f"{pass_name}-fy{shard_start}-fy{shard_end}",
                    "pass_name": pass_name,
                    "fy_start": shard_start,
                    "fy_end": shard_end,
                    "timeout_minutes": GRANTS_SHARD_TIMEOUT_MINUTES,
                }
            )
    return shards


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

    keyless = [keyless_by_id[source_id] for source_id in sorted(keyless_by_id)]
    standard_keyless = [item for item in keyless if item["source"] != GRANTS_SOURCE_ID]
    grants_shards = build_grants_shard_plan() if GRANTS_SOURCE_ID in keyless_by_id else []
    return {
        "keyless": keyless,
        "standard_keyless": standard_keyless,
        "grants_shards": grants_shards,
        "credential_gated": [credential_by_id[source_id] for source_id in sorted(credential_by_id)],
    }
