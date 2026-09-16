from __future__ import annotations

import copy

import pytest

from scripts.audit_guide_financial_avenues import (
    compute,
    load_inputs,
    metrics_payload,
    validate_inputs,
)


def test_frozen_guide_and_161_source_denominators_close():
    """As of 2026-09-12 the frozen base-source snapshot was extended in place

    from 158 to 161 sources (see reports/guide_financial_avenue_coverage_v1.md,
    "2026-09-12 update"), by exactly the 3 sources that close GFAV-004/005/020.
    """
    inputs = load_inputs()
    validated = validate_inputs(inputs)
    computed = compute(inputs, validated)
    metrics = metrics_payload(inputs, validated, computed)

    assert len(validated["avenue_ids"]) == 30
    assert len(validated["source_ids"]) == 161

    guide_projection = metrics["guide_projection"]
    assert guide_projection["intersection_count"] == 30
    assert guide_projection["a_only_count"] == 0
    assert guide_projection["b_only_count"] == 0
    assert guide_projection["union_count"] == 30
    assert guide_projection["symmetric_difference_count"] == 0
    assert guide_projection["a_only"] == []

    source_projection = metrics["source_projection"]
    assert source_projection["intersection_count"] == 21
    assert source_projection["b_only_count"] == 140
    assert source_projection["intersection_count"] + source_projection["b_only_count"] == 161

    assert metrics["certification_state"] == "OPEN"


def test_promoted_sources_are_no_longer_staged_in_the_overlay():
    inputs = load_inputs()
    validated = validate_inputs(inputs)

    # ocif_guide_financial_classes / ocs_insurer_registry / ftz_board_pr were
    # promoted into the base registry; the guide-avenue overlay that staged them
    # is emptied, not left duplicating base source_ids (the audit fails closed
    # on any overlay/base collision).
    assert validated["overlay_ids"] == []

    computed = compute(inputs, validated)
    assert computed["avenue_sets"]["A_ONLY"] == []


def test_binding_states_never_promote_discovery_to_identity():
    inputs = load_inputs()
    validate_inputs(inputs)
    bindings = inputs["bindings"]["bindings"]
    assert bindings["GFAV-006"]["state"] == "CANDIDATE_NOT_IDENTITY"
    assert bindings["GFAV-007"]["state"] == "CANDIDATE_NOT_IDENTITY"
    assert bindings["GFAV-004"]["state"] == "AUTHORITATIVE_ROUTE"
    assert bindings["GFAV-005"]["state"] == "AUTHORITATIVE_ROUTE"
    assert bindings["GFAV-020"]["state"] == "AUTHORITATIVE_ROUTE"


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
