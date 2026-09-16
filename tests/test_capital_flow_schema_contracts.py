from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, ValidationError


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schemas" / "capital_flow_observation.schema.json"


def _schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _valid_flow() -> dict:
    return {
        "observation_id": "FLOW_PR_FY2025_TEST",
        "source_entity_id": "ENTITY_PR",
        "destination_entity_id": "ENTITY_NONRESIDENT",
        "amount": 100.0,
        "currency": "USD",
        "period_start": "2024-07-01",
        "period_end": "2025-06-30",
        "measurement_type": "FLOW",
        "economic_category": "DIRECT_INVESTMENT_EARNINGS",
        "flow_direction": "OUT_OF_PR",
        "source_jurisdiction": "PR",
        "destination_jurisdiction": "UNKNOWN",
        "pr_retention_state": "ACCRUES_NONRESIDENT",
        "source_manifestation_id": "manifest:test",
        "source_record_id": "row:1",
        "certification_state": "PROVISIONAL",
    }


def test_schema_is_valid_draft_2020_12() -> None:
    Draft202012Validator.check_schema(_schema())


def test_measurement_taxonomy_preserves_stock_flow_distinction() -> None:
    values = set(_schema()["properties"]["measurement_type"]["enum"])
    assert values == {"FLOW", "STOCK", "RATE", "BALANCE", "VALUATION", "COUNT", "UNKNOWN"}


def test_direction_taxonomy_is_symmetric_and_preserves_unknown() -> None:
    values = set(_schema()["properties"]["flow_direction"]["enum"])
    assert values == {"INTO_PR", "WITHIN_PR", "OUT_OF_PR", "THROUGH_PR", "UNKNOWN"}


def test_unknown_is_distinct_from_zero() -> None:
    row = _valid_flow()
    row["amount"] = 0
    Draft202012Validator(_schema()).validate(row)
    row["flow_direction"] = "UNKNOWN"
    Draft202012Validator(_schema()).validate(row)


def test_facility_parent_and_beneficial_owner_are_separate_fields() -> None:
    props = _schema()["properties"]
    assert "facility_location" in props
    assert "immediate_parent_id" in props
    assert "ultimate_parent_id" in props
    assert "beneficial_owner_id" in props
    assert len({"facility_location", "immediate_parent_id", "ultimate_parent_id", "beneficial_owner_id"}) == 4


def test_flow_requires_amount_and_retention_state() -> None:
    validator = Draft202012Validator(_schema())
    row = _valid_flow()
    validator.validate(row)

    missing_amount = dict(row)
    missing_amount.pop("amount")
    with pytest.raises(ValidationError):
        validator.validate(missing_amount)

    missing_retention = dict(row)
    missing_retention.pop("pr_retention_state")
    with pytest.raises(ValidationError):
        validator.validate(missing_retention)


def test_cross_boundary_flow_requires_both_jurisdictions() -> None:
    validator = Draft202012Validator(_schema())
    row = _valid_flow()
    for field in ("source_jurisdiction", "destination_jurisdiction"):
        broken = dict(row)
        broken.pop(field)
        with pytest.raises(ValidationError):
            validator.validate(broken)


def test_macro_aggregate_does_not_require_entity_assignment() -> None:
    row = _valid_flow()
    row["source_entity_id"] = None
    row["destination_entity_id"] = None
    row["economic_category"] = "NET_FACTOR_INCOME_REST_OF_WORLD"
    Draft202012Validator(_schema()).validate(row)


def test_certification_states_include_open_and_unresolved() -> None:
    states = set(_schema()["properties"]["certification_state"]["enum"])
    assert {"PASS", "FAIL", "OPEN", "BLOCKED", "PROVISIONAL", "AUDIT_ONLY", "UNRESOLVED"} <= states
