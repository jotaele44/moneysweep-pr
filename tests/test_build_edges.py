"""Tests for the canonical_v1 edge builder (WS-M)."""

from pathlib import Path

import pytest

from contract_sweeper.runtime.canonical_ids import edge_id
from contract_sweeper.validation import canonical_v1_schema as cv1
from scripts import build_edges as be

REPO_ROOT = cv1.REPO_ROOT
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "canonical_v1_relationships_sample.csv"


@pytest.mark.integration
def test_builds_all_seeded_edge_types():
    built = be.build_edges(REPO_ROOT)
    by_type: dict[str, int] = {}
    for e in built["edge_rows"]:
        by_type[e["edge_type"]] = by_type.get(e["edge_type"], 0) + 1
    assert built["skipped"] == []
    # 10 entity->muni + 5 project->muni LOCATED_IN
    # LOCATED_IN: 10 entity->muni + 5 project->muni + 4 property->muni
    assert by_type == {
        "LOCATED_IN": 19,
        "HOLDS_ROLE_IN": 7,
        "HOLDS_DEBT": 20,
        "ADVISES": 5,
        "OWNS_OR_CONTROLS": 3,
        "FUNDED_BY": 4,
        "RECEIVES_CONTRACT": 3,
        "LOBBIES_FOR": 3,
    }
    assert len(built["edge_rows"]) == 64


@pytest.mark.integration
def test_property_located_in_edges():
    built = be.build_edges(REPO_ROOT)
    tables = cv1.load_all_tables(REPO_ROOT)
    property_ids = {r["property_id"] for r in tables["properties"]}
    muni_ids = {r["municipality_id"] for r in tables["municipalities"]}
    prop_edges = [
        e
        for e in built["edge_rows"]
        if e["edge_type"] == "LOCATED_IN" and e["source_node_type"] == "Property"
    ]
    assert len(prop_edges) == len(tables["properties"])
    for e in prop_edges:
        assert e["source_node_id"] in property_ids
        assert e["target_node_id"] in muni_ids


@pytest.mark.integration
def test_lobbies_for_edges_are_entity_to_entity():
    built = be.build_edges(REPO_ROOT)
    entity_ids = {r["entity_id"] for r in cv1.load_all_tables(REPO_ROOT)["entities"]}
    lf = [e for e in built["edge_rows"] if e["edge_type"] == "LOBBIES_FOR"]
    assert len(lf) == 3
    for e in lf:
        assert e["source_node_type"] == "Entity"
        assert e["source_node_id"] in entity_ids
        assert e["target_node_type"] == "Entity"
        assert e["target_node_id"] in entity_ids


@pytest.mark.integration
def test_receives_contract_edges_are_entity_to_contract():
    built = be.build_edges(REPO_ROOT)
    tables = cv1.load_all_tables(REPO_ROOT)
    entity_ids = {r["entity_id"] for r in tables["entities"]}
    contract_ids = {r["contract_id"] for r in tables["contracts"]}
    rc = [e for e in built["edge_rows"] if e["edge_type"] == "RECEIVES_CONTRACT"]
    assert len(rc) == 3
    for e in rc:
        assert e["source_node_type"] == "Entity"
        assert e["source_node_id"] in entity_ids
        assert e["target_node_type"] == "Contract"
        assert e["target_node_id"] in contract_ids


@pytest.mark.integration
def test_funded_by_edges_are_project_to_funding_source():
    built = be.build_edges(REPO_ROOT)
    tables = cv1.load_all_tables(REPO_ROOT)
    project_ids = {r["project_id"] for r in tables["projects"]}
    funding_ids = {r["funding_source_id"] for r in tables["funding_sources"]}
    funded = [e for e in built["edge_rows"] if e["edge_type"] == "FUNDED_BY"]
    assert len(funded) == 4
    for e in funded:
        assert e["source_node_type"] == "Project"
        assert e["source_node_id"] in project_ids
        assert e["target_node_type"] == "FundingSource"
        assert e["target_node_id"] in funding_ids


@pytest.mark.integration
def test_owns_or_controls_edges_are_operator_to_project():
    built = be.build_edges(REPO_ROOT)
    tables = cv1.load_all_tables(REPO_ROOT)
    entity_ids = {r["entity_id"] for r in tables["entities"]}
    project_ids = {r["project_id"] for r in tables["projects"]}
    control = [e for e in built["edge_rows"] if e["edge_type"] == "OWNS_OR_CONTROLS"]
    assert len(control) == 3
    for e in control:
        assert e["source_node_type"] == "Entity"
        assert e["source_node_id"] in entity_ids
        assert e["target_node_type"] == "Project"
        assert e["target_node_id"] in project_ids


@pytest.mark.unit
def test_resolver_resolves_project_targets():
    resolver = be.build_resolver(REPO_ROOT)
    pid = be.resolve(resolver, "Project", "PRASA Capital Improvement Program")
    assert pid and pid.startswith("project_")


@pytest.mark.integration
def test_project_located_in_edges():
    built = be.build_edges(REPO_ROOT)
    tables = cv1.load_all_tables(REPO_ROOT)
    project_ids = {r["project_id"] for r in tables["projects"]}
    muni_ids = {r["municipality_id"] for r in tables["municipalities"]}
    proj_edges = [
        e
        for e in built["edge_rows"]
        if e["edge_type"] == "LOCATED_IN" and e["source_node_type"] == "Project"
    ]
    assert len(proj_edges) == len(tables["projects"])
    for e in proj_edges:
        assert e["source_node_id"] in project_ids
        assert e["target_node_id"] in muni_ids


@pytest.mark.integration
def test_advises_edges_are_entity_to_entity():
    built = be.build_edges(REPO_ROOT)
    entity_ids = {r["entity_id"] for r in cv1.load_all_tables(REPO_ROOT)["entities"]}
    advises = [e for e in built["edge_rows"] if e["edge_type"] == "ADVISES"]
    assert len(advises) == 5
    for e in advises:
        assert e["source_node_type"] == "Entity"
        assert e["target_node_type"] == "Entity"
        assert e["source_node_id"] in entity_ids
        assert e["target_node_id"] in entity_ids


@pytest.mark.integration
def test_holds_debt_edges_link_entity_to_debt():
    built = be.build_edges(REPO_ROOT)
    tables = cv1.load_all_tables(REPO_ROOT)
    entity_ids = {r["entity_id"] for r in tables["entities"]}
    debt_ids = {r["debt_id"] for r in tables["debt_instruments"]}
    debt_edges = [e for e in built["edge_rows"] if e["edge_type"] == "HOLDS_DEBT"]
    assert len(debt_edges) == len(tables["debt_instruments"])
    for e in debt_edges:
        assert e["source_node_type"] == "Entity"
        assert e["source_node_id"] in entity_ids
        assert e["target_node_type"] == "DebtInstrument"
        assert e["target_node_id"] in debt_ids


@pytest.mark.integration
def test_edges_validate_and_endpoints_resolve():
    built = be.build_edges(REPO_ROOT)
    edge_schema = cv1.load_schema("edges", REPO_ROOT)
    tables = cv1.load_all_tables(REPO_ROOT)
    entity_ids = {r["entity_id"] for r in tables["entities"]}
    muni_ids = {r["municipality_id"] for r in tables["municipalities"]}
    person_ids = {r["person_id"] for r in tables["people"]}
    project_ids = {r["project_id"] for r in tables["projects"]}
    # evidence may come from the seed (built here) or from roles.csv (already on disk)
    evidence_ids = {e.evidence_id for e in built["evidence_rows"]}
    evidence_ids |= {r["evidence_id"] for r in tables["evidence"]}
    for e in built["edge_rows"]:
        assert cv1.validate_row(e, edge_schema) == [], e
        assert e["evidence_id"] in evidence_ids  # no provenance -> no edge
        assert e["edge_type"] in cv1.EDGE_TYPES  # controlled vocab
        if e["edge_type"] == "LOCATED_IN":
            # LOCATED_IN sources are Entity, Project, or Property; targets are munis
            property_ids = {r["property_id"] for r in tables["properties"]}
            assert e["source_node_id"] in (entity_ids | project_ids | property_ids)
            assert e["target_node_id"] in muni_ids
        elif e["edge_type"] == "HOLDS_ROLE_IN":
            assert e["source_node_type"] == "Person"
            assert e["source_node_id"] in person_ids
            assert e["target_node_type"] == "Entity"
            assert e["target_node_id"] in entity_ids


@pytest.mark.integration
def test_holds_role_in_edges_match_roles_table():
    """One HOLDS_ROLE_IN edge per role row, reusing the role's evidence."""
    built = be.build_edges(REPO_ROOT)
    roles = be._read_roles(REPO_ROOT)
    role_edges = [e for e in built["edge_rows"] if e["edge_type"] == "HOLDS_ROLE_IN"]
    assert len(role_edges) == len(roles)
    role_ev = {r["evidence_id"] for r in roles}
    for e in role_edges:
        assert e["evidence_id"] in role_ev
        assert e["edge_id"] == edge_id(e["source_node_id"], "HOLDS_ROLE_IN", e["target_node_id"])


@pytest.mark.unit
def test_resolver_handles_aliases_and_normalization():
    resolver = be.build_resolver(REPO_ROOT)
    # alias "PREPA" (stored in entity notes) resolves to the PREPA node
    prepa_full = be.resolve(resolver, "Entity", "Puerto Rico Electric Power Authority")
    prepa_alias = be.resolve(resolver, "Entity", "PREPA")
    assert prepa_full and prepa_full == prepa_alias
    assert be.resolve(resolver, "Municipality", "San Juan") is not None


@pytest.mark.integration
def test_uncontrolled_verb_and_unresolved_endpoints_are_skipped(monkeypatch, tmp_path):
    monkeypatch.setattr(be, "RELATIONSHIPS", str(FIXTURE))
    # isolate from the on-disk roles/debt/project tables so we test only the seed rows
    monkeypatch.setattr(be, "ROLES_IN", str(tmp_path / "no_roles.csv"))
    monkeypatch.setattr(be, "DEBT_IN", str(tmp_path / "no_debt.csv"))
    monkeypatch.setattr(be, "PROJECTS_IN", str(tmp_path / "no_projects.csv"))
    monkeypatch.setattr(be, "CONTRACTS_IN", str(tmp_path / "no_contracts.csv"))
    monkeypatch.setattr(be, "LOBBYING_IN", str(tmp_path / "no_lobbying.csv"))
    monkeypatch.setattr(be, "PROPERTIES_TABLE_IN", str(tmp_path / "no_properties.csv"))
    monkeypatch.setattr(be, "FUNDING_LINKS", str(tmp_path / "no_funding_links.csv"))
    built = be.build_edges(REPO_ROOT)
    assert len(built["edge_rows"]) == 1  # only the valid PREPA->San Juan row
    reasons = " ".join(s["reason"] for s in built["skipped"])
    assert "uncontrolled edge_type" in reasons
    assert "unresolved source" in reasons
    assert "unresolved target" in reasons


@pytest.mark.unit
def test_edge_id_is_deterministic():
    built = be.build_edges(REPO_ROOT)
    e = built["edge_rows"][0]
    assert e["edge_id"] == edge_id(e["source_node_id"], e["edge_type"], e["target_node_id"])
