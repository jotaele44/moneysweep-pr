"""Structural and drift gates for the 25-domain financial-intelligence ontology."""

import copy
import json
from pathlib import Path

import pytest

from moneysweep.entity_network.policy import _MONEY_FLOW_RELATION_TYPES
from moneysweep.financial_intelligence import (
    DOMAIN_IDS,
    OntologyError,
    load_ontology,
    unresolved_foundation_bindings,
    validate_ontology,
)
from moneysweep.financial_intelligence.coverage import (
    BINDINGS_PATH,
    build_coverage,
    load_bindings,
    main,
    read_audit_rows,
)
from moneysweep.financial_intelligence.ontology import ONTOLOGY_PATH, REPO_ROOT

SCHEMA_PATH = REPO_ROOT / "schemas" / "financial_intelligence_ontology.schema.json"


@pytest.fixture(scope="module")
def ontology():
    return load_ontology()


def mutated(ontology, mutate):
    data = copy.deepcopy(ontology)
    mutate(data)
    return data


def test_registry_matches_its_schema(ontology):
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.Draft202012Validator(schema).validate(ontology)


def test_denominators_match_the_proposal(ontology):
    assert tuple(d["id"] for d in ontology["domains"]) == DOMAIN_IDS
    assert len(ontology["foreign_connection_classes"]) == 9
    flow = ontology["flow_model"]
    assert len(flow["geographic_axis"]) + len(flow["characters"]) == 8
    assert [len(g["kinds"]) for g in ontology["entity_universe"]] == [6] * 6
    assert len(ontology["continuity_dimensions"]) == 7
    assert len(ontology["historical_scope"]["periods"]) == 7
    assert len(ontology["capabilities"]) == 20
    assert len(ontology["infrastructure_classes"]) == 14
    assert len(ontology["scope_policy"]) == 10
    assert len(ontology["core_questions"]) == 6


def test_candidate_is_not_adopted(ontology):
    assert ontology["status"] == "CANDIDATE_NOT_ADOPTED"
    assert ontology["certification"] == "WITHHELD"
    assert ontology["production_adoption"] == "BLOCKED"
    assert all(d["population_state"] == "DEFINED_NOT_POPULATED" for d in ontology["domains"])


def test_every_reused_primitive_still_resolves(ontology):
    assert unresolved_foundation_bindings(ontology) == []


def test_a_renamed_primitive_is_reported(ontology):
    data = mutated(ontology, lambda d: d["foundations"][0]["symbols"].append("no_such_symbol"))
    assert unresolved_foundation_bindings(data) == [
        "moneysweep.capital_control.resolution_core.no_such_symbol"
    ]


def test_capital_relationships_are_money_flows_not_graph_edges(ontology):
    capital = next(c for c in ontology["foreign_connection_classes"] if c["id"] == "FC01")
    assert capital["kernel_binding"] == "MONEY_FLOW"
    assert {"INVESTS_IN", "LENDS_TO"} <= _MONEY_FLOW_RELATION_TYPES


def test_moneysweep_owns_no_infrastructure_registry(ontology):
    owners = {i["identity_owner_candidate"] for i in ontology["infrastructure_classes"]}
    assert "moneysweep-pr" not in owners
    assert all(i["owner_state"] != "RATIFIED" for i in ontology["infrastructure_classes"])


def test_secondary_sources_establish_nothing(ontology):
    for tier in ontology["source_authority_hierarchy"]:
        if tier["evidence_tier"] == "T4":
            assert tier["may_establish"] == []


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d["domains"].pop(),
        lambda d: d["domains"].__setitem__(0, {**d["domains"][0], "id": "MS02"}),
        lambda d: d["domains"][3].__setitem__("reuses_foundations", ["F99"]),
        lambda d: d["domains"][3].__setitem__("priority", "P9"),
        lambda d: d.__setitem__("production_adoption", "AUTHORIZED"),
        lambda d: d["infrastructure_classes"][0].__setitem__(
            "identity_owner_candidate", "moneysweep-pr"
        ),
        lambda d: d["infrastructure_classes"][3].__setitem__("owner_state", "RATIFIED"),
        lambda d: d["foreign_connection_classes"][1].__setitem__("kernel_binding", "PAYS"),
        lambda d: d["flow_model"]["characters"].pop(),
        lambda d: d["continuity_dimensions"][0]["states"].append("ZOMBIE"),
        lambda d: d["historical_scope"].__setitem__("baseline_year", 1900),
        lambda d: d["historical_scope"].__setitem__("periods_are_mutually_exclusive", True),
        lambda d: d["capabilities"][0].__setitem__("guardrail", " "),
        lambda d: d["source_authority_hierarchy"][-1].__setitem__("may_establish", ["identity"]),
        lambda d: d["entity_universe"][0]["kinds"][0].__setitem__("node_kind", "SUSPECT"),
    ],
)
def test_structural_drift_fails_closed(ontology, mutate):
    with pytest.raises(OntologyError):
        validate_ontology(mutated(ontology, mutate))


# --- source-level candidate coverage -----------------------------------------


@pytest.fixture(scope="module")
def coverage_inputs(ontology):
    bindings = load_bindings()
    rows = read_audit_rows(REPO_ROOT / bindings["denominator"]["path"])
    return ontology, bindings, rows


def test_source_denominator_is_conserved(coverage_inputs):
    ontology, bindings, rows = coverage_inputs
    coverage = build_coverage(ontology, bindings, rows)
    den = coverage["denominator"]
    assert den["conserved"] is True
    assert den["bound"] + den["explicitly_unbound"] + den["unclassified"] == den["audit_rows"]
    assert coverage["certification"] == "WITHHELD"
    assert coverage["row_classification"] == "OPEN"
    assert set(coverage["domains"]) == set(DOMAIN_IDS)


def test_a_new_registry_source_is_reported_not_silently_dropped(coverage_inputs):
    ontology, bindings, rows = coverage_inputs
    extra = rows + [{"source_id": "brand_new_source", "audit_status": "queued_manual"}]
    coverage = build_coverage(ontology, bindings, extra)
    assert coverage["unclassified_sources"] == ["brand_new_source"]
    assert coverage["denominator"]["conserved"] is True


def test_phantom_and_contradictory_bindings_fail_closed(coverage_inputs):
    ontology, bindings, rows = coverage_inputs
    phantom = copy.deepcopy(bindings)
    phantom["bindings"]["not_in_registry"] = ["MS03"]
    with pytest.raises(ValueError, match="unregistered"):
        build_coverage(ontology, phantom, rows)

    both = copy.deepcopy(bindings)
    both["unbound"]["fec"] = "contradiction"
    with pytest.raises(ValueError, match="both bound and unbound"):
        build_coverage(ontology, both, rows)

    unknown = copy.deepcopy(bindings)
    unknown["bindings"]["fec"] = ["MS99"]
    with pytest.raises(ValueError, match="unknown domain"):
        build_coverage(ontology, unknown, rows)


def test_committed_coverage_report_is_current():
    assert Path(ONTOLOGY_PATH).exists() and Path(BINDINGS_PATH).exists()
    assert main(["--check"]) == 0
