from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

import pytest

from tools.keyless_execution_plan import (
    DEFAULT_TIMEOUT_MINUTES,
    GRANTS_PASSES,
    GRANTS_SHARD_TIMEOUT_MINUTES,
    GRANTS_SOURCE_ID,
    MAX_TIMEOUT_MINUTES,
    build_grants_shard_plan,
    build_execution_plan,
    current_fiscal_year,
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
    assert plan["standard_keyless"] == [
        {"source": "quick", "timeout_minutes": DEFAULT_TIMEOUT_MINUTES},
        {"source": "rdc_demandas_civiles", "timeout_minutes": 180},
    ]
    assert plan["grants_shards"] == build_grants_shard_plan()
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


def test_current_fiscal_year_changes_on_october_boundary() -> None:
    assert current_fiscal_year(date(2026, 9, 30)) == 2026
    assert current_fiscal_year(date(2026, 10, 1)) == 2027


def test_grants_shard_plan_closes_source_year_arithmetic() -> None:
    plan = build_grants_shard_plan(start_fy=2000, end_fy=2027, span=7)

    assert len(plan) == 16
    assert {item["pass_name"] for item in plan} == set(GRANTS_PASSES)
    assert all(item["timeout_minutes"] == GRANTS_SHARD_TIMEOUT_MINUTES for item in plan)
    cells = {
        (item["pass_name"], fiscal_year)
        for item in plan
        for fiscal_year in range(item["fy_start"], item["fy_end"] + 1)
    }
    assert len(cells) == 4 * 28 == 112
    assert cells == {
        (pass_name, fiscal_year) for pass_name in GRANTS_PASSES for fiscal_year in range(2000, 2028)
    }


@pytest.mark.parametrize(
    ("kwargs", "error"),
    [
        ({"start_fy": True}, TypeError),
        ({"end_fy": 0}, ValueError),
        ({"start_fy": 2027, "end_fy": 2026}, ValueError),
        ({"span": 0}, ValueError),
        ({"span": 1.5}, TypeError),
    ],
)
def test_grants_shard_plan_rejects_invalid_ranges(
    kwargs: dict[str, object], error: type[Exception]
) -> None:
    with pytest.raises(error):
        build_grants_shard_plan(**kwargs)  # type: ignore[arg-type]


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
    assert {item["source"] for item in plan["standard_keyless"]} == (
        {item["source"] for item in plan["keyless"]} - {GRANTS_SOURCE_ID}
    )
    assert len(plan["keyless"]) == 107
    assert len(plan["standard_keyless"]) == 106
    assert plan["grants_shards"] == build_grants_shard_plan()
    assert overridden == {
        "grants_gov": MAX_TIMEOUT_MINUTES,
        "rdc_demandas_civiles": 180,
    }
