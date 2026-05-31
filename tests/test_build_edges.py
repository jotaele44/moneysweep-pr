"""Tests for the canonical_v1 edge builder (WS-M)."""
from pathlib import Path

import pytest

from contract_sweeper.runtime.canonical_ids import edge_id
from contract_sweeper.validation import canonical_v1_schema as cv1
from scripts import build_edges as be

REPO_ROOT = cv1.REPO_ROOT
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "canonical_v1_relationships_sample.csv"


@pytest.mark.integration
def test_seed_builds_located_in_edges():
    built = be.build_edges(REPO_ROOT)
    assert len(built["edge_rows"]) == 10
    assert built["skipped"] == []
    assert {e["edge_type"] for e in built["edge_rows"]} == {"LOCATED_IN"}


@pytest.mark.integration
def test_edges_validate_and_endpoints_resolve():
    built = be.build_edges(REPO_ROOT)
    edge_schema = cv1.load_schema("edges", REPO_ROOT)
    tables = cv1.load_all_tables(REPO_ROOT)
    entity_ids = {r["entity_id"] for r in tables["entities"]}
    muni_ids = {r["municipality_id"] for r in tables["municipalities"]}
    evidence_ids = {e.evidence_id for e in built["evidence_rows"]}
    for e in built["edge_rows"]:
        assert cv1.validate_row(e, edge_schema) == [], e
        assert e["source_node_id"] in entity_ids
        assert e["target_node_id"] in muni_ids
        assert e["evidence_id"] in evidence_ids          # no provenance -> no edge
        assert e["edge_type"] in cv1.EDGE_TYPES          # controlled vocab


@pytest.mark.unit
def test_resolver_handles_aliases_and_normalization():
    resolver = be.build_resolver(REPO_ROOT)
    # alias "PREPA" (stored in entity notes) resolves to the PREPA node
    prepa_full = be.resolve(resolver, "Entity", "Puerto Rico Electric Power Authority")
    prepa_alias = be.resolve(resolver, "Entity", "PREPA")
    assert prepa_full and prepa_full == prepa_alias
    assert be.resolve(resolver, "Municipality", "San Juan", ) is not None


@pytest.mark.integration
def test_uncontrolled_verb_and_unresolved_endpoints_are_skipped(monkeypatch):
    monkeypatch.setattr(be, "RELATIONSHIPS", str(FIXTURE))
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
