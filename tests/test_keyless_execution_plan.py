from __future__ import annotations

import csv
from pathlib import Path

import pytest

from tools.keyless_execution_plan import (
    DEFAULT_TIMEOUT_MINUTES,
    MAX_TIMEOUT_MINUTES,
    build_execution_plan,
    execution_timeout_minutes,
)


def test_slow_sources_receive_bounded_overrides() -> None:
    status_rows = [
        {
            "source_id": "quick",
            "authentication": "none",
            "producer_script": "scripts/quick.py",
        },
        {
            "source_id": "grants_gov",
            "authentication": "none",
            "producer_script": "scripts/download_grants.py",
        },
        {
            "source_id": "rdc_demandas_civiles",
            "authentication": "none",
            "producer_script": "scripts/scrape_rdc_demandas.py",
        },
        {
            "source_id": "credentialed",
            "authentication": "api_key",
            "producer_script": "scripts/credentialed.py",
        },
    ]
    recovery_rows = [
        {"source_id": "quick", "automatable": "true"},
        {"source_id": "grants_gov", "automatable": "TRUE"},
        {"source_id": "rdc_demandas_civiles", "automatable": "true"},
        {"source_id": "credentialed", "automatable": "true"},
    ]

    plan = build_execution_plan(status_rows, recovery_rows)

    assert plan["keyless"] == [
        {"source": "grants_gov", "timeout_minutes": MAX_TIMEOUT_MINUTES},
        {"source": "quick", "timeout_minutes": DEFAULT_TIMEOUT_MINUTES},
        {"source": "rdc_demandas_civiles", "timeout_minutes": 180},
    ]
    assert plan["credential_gated"] == [
        {
            "source_id": "credentialed",
            "authentication": "api_key",
            "producer_script": "scripts/credentialed.py",
        }
    ]


@pytest.mark.parametrize("timeout", [0, MAX_TIMEOUT_MINUTES + 1, True, 1.5])
def test_timeout_policy_rejects_invalid_values(timeout: object) -> None:
    error = TypeError if isinstance(timeout, (bool, float)) else ValueError
    with pytest.raises(error):
        execution_timeout_minutes("fixture", overrides={"fixture": timeout})  # type: ignore[arg-type]


def test_plan_rejects_duplicate_or_unbound_source_rows() -> None:
    with pytest.raises(ValueError, match="duplicate source status row"):
        build_execution_plan(
            [
                {"source_id": "fixture", "authentication": "none"},
                {"source_id": "fixture", "authentication": "none"},
            ],
            [{"source_id": "fixture", "automatable": "true"}],
        )

    with pytest.raises(ValueError, match="missing status row"):
        build_execution_plan(
            [],
            [{"source_id": "fixture", "automatable": "true"}],
        )


def test_repository_plan_partitions_the_full_automatable_denominator() -> None:
    with Path("reports/source_registry_status.csv").open(
        encoding="utf-8-sig", newline=""
    ) as status_file:
        status_rows = list(csv.DictReader(status_file))
    with Path("reports/source_recovery_matrix.csv").open(
        encoding="utf-8-sig", newline=""
    ) as recovery_file:
        recovery_rows = list(csv.DictReader(recovery_file))

    plan = build_execution_plan(status_rows, recovery_rows)
    automatable_ids = {
        row["source_id"] for row in recovery_rows if row["automatable"].strip().lower() == "true"
    }
    planned_ids = {item["source"] for item in plan["keyless"]} | {
        item["source_id"] for item in plan["credential_gated"]
    }
    overridden = {
        item["source"]: item["timeout_minutes"]
        for item in plan["keyless"]
        if item["timeout_minutes"] != DEFAULT_TIMEOUT_MINUTES
    }

    assert planned_ids == automatable_ids
    assert len(planned_ids) == 119
    assert overridden == {
        "grants_gov": MAX_TIMEOUT_MINUTES,
        "rdc_demandas_civiles": 180,
    }
