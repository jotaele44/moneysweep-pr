from __future__ import annotations

import copy

import pytest

from scripts.audit_guide_financial_avenues import (
    compute,
    load_inputs,
    metrics_payload,
    validate_inputs,
)


def test_frozen_guide_and_158_source_denominators_close():
    inputs = load_inputs()
    validated = validate_inputs(inputs)
    computed = compute(inputs, validated)
    metrics = metrics_payload(inputs, validated, computed)

    assert len(validated["avenue_ids"]) == 30
    assert len(validated["source_ids"]) == 158

    guide_projection = metrics["guide_projection"]
    assert guide_projection["intersection_count"] == 27
    assert guide_projection["a_only_count"] == 3
    assert guide_projection["b_only_count"] == 0
    assert guide_projection["union_count"] == 30
    assert guide_projection["symmetric_difference_count"] == 3
    assert guide_projection["a_only"] == ["GFAV-004", "GFAV-005", "GFAV-020"]

    source_projection = metrics["source_projection"]
    assert source_projection["intersection_count"] == 18
    assert source_projection["b_only_count"] == 140
    assert source_projection["intersection_count"] + source_projection["b_only_count"] == 158

    assert metrics["certification_state"] == "OPEN"


def test_overlay_is_additive_and_closes_only_source_routes():
    inputs = load_inputs()
    validated = validate_inputs(inputs)
    assert set(validated["overlay_ids"]) == {
        "ocif_guide_financial_classes",
        "ocs_insurer_registry",
        "ftz_board_pr",
    }

    # Overlay registration is deliberately not counted as current base coverage.
    computed = compute(inputs, validated)
    assert computed["avenue_sets"]["A_ONLY"] == ["GFAV-004", "GFAV-005", "GFAV-020"]


def test_binding_states_never_promote_discovery_to_identity():
    inputs = load_inputs()
    validate_inputs(inputs)
    bindings = inputs["bindings"]["bindings"]
    assert bindings["GFAV-006"]["state"] == "CANDIDATE_NOT_IDENTITY"
    assert bindings["GFAV-007"]["state"] == "CANDIDATE_NOT_IDENTITY"
    assert bindings["GFAV-004"]["state"] == "ABSENT"
    assert bindings["GFAV-005"]["state"] == "ABSENT"
    assert bindings["GFAV-020"]["state"] == "ABSENT"


def test_frozen_source_membership_hash_fails_closed():
    inputs = copy.deepcopy(load_inputs())
    inputs["snapshot_rows"][0]["source_id"] = "substituted-source"

    with pytest.raises(RuntimeError, match="snapshot hash drift"):
        validate_inputs(inputs)


def test_frozen_source_missing_from_live_registry_fails_closed():
    inputs = copy.deepcopy(load_inputs())
    missing = inputs["snapshot_rows"][0]["source_id"]
    inputs["registry"]["sources"] = [
        row for row in inputs["registry"]["sources"] if row["source_id"] != missing
    ]

    with pytest.raises(RuntimeError, match="missing from live registry"):
        validate_inputs(inputs)
