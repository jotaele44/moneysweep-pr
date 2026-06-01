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
    assert by_type == {"LOCATED_IN": 15, "HOLDS_ROLE_IN": 7, "HOLDS_DEBT": 20, "ADVISES": 5}
    assert len(built["edge_rows"]) == 47


@pytest.mark.integration
def test_project_located_in_edges():
    built = be.build_edges(REPO_ROOT)
    tables = cv1.load_all_tables(REPO_ROOT)
    project_ids = {r["project_id"] for r in tables["projects"]}
    muni_ids = {r["municipality_id"] for r in tables["municipalities"]}
    proj_edges = [e for e in built["edge_rows"]
                  if e["edge_type"] == "LOCATED_IN" and e["source_node_type"] == "Project"]
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
        assert e["evidence_id"] in evidence_ids          # no provenance -> no edge
        assert e["edge_type"] in cv1.EDGE_TYPES          # controlled vocab
        if e["edge_type"] == "LOCATED_IN":
            # LOCATED_IN sources are Entity or Project; targets are municipalities
            assert e["source_node_id"] in (entity_ids | project_ids)
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
    built = be.build_edges(REPO_ROOT)
    assert len(built["edge_rows"]) == 1                  # only the valid PREPA->San Juan row
    reasons = " ".join(s["reason"] for s in built["skipped"])
    assert "uncontrolled edge_type" in reasons
    assert "unresolved source" in reasons
    assert "unresolved target" in reasons


@pytest.mark.unit
def test_edge_id_is_deterministic():
    built = be.build_edges(REPO_ROOT)
    e = built["edge_rows"][0]
    assert e["edge_id"] == edge_id(e["source_node_id"], e["edge_type"], e["target_node_id"])
