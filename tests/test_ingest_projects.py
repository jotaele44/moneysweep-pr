"""Tests for the canonical_v1 projects ingester (WS-G)."""

import pytest

from moneysweep.validation import canonical_v1_schema as cv1
from scripts import ingest_projects as ip

REPO_ROOT = cv1.REPO_ROOT


@pytest.fixture(scope="module")
def built():
    return ip.build_rows(REPO_ROOT)


@pytest.mark.integration
def test_seed_projects_resolve_lead_entities(built):
    rows = built["project_rows"]
    assert len(rows) == 5
    assert built["skipped"] == []
    assert ip.check(rows) == []
    assert {r["project_type"] for r in rows} == {"ppp", "recovery", "infrastructure"}


@pytest.mark.integration
def test_rows_and_evidence_validate(built):
    proj_schema = cv1.load_schema("projects", REPO_ROOT)
    ev_schema = cv1.load_schema("evidence", REPO_ROOT)
    tables = cv1.load_all_tables(REPO_ROOT)
    entity_ids = {r["entity_id"] for r in tables["entities"]}
    muni_ids = {r["municipality_id"] for r in tables["municipalities"]}
    evidence_ids = {e.evidence_id for e in built["evidence_rows"]}
    for row in built["project_rows"]:
        assert cv1.validate_row(row, proj_schema) == [], row
        assert row["lead_entity_id"] in entity_ids  # no broken reference
        assert row["evidence_id"] in evidence_ids  # no provenance -> no row
        if row["municipality_id"]:
            assert row["municipality_id"] in muni_ids
    for ev in built["evidence_rows"]:
        assert cv1.validate_row(ev.as_row(), ev_schema) == [], ev


@pytest.mark.unit
def test_project_ids_unique_and_deterministic(built):
    rows = built["project_rows"]
    ids = [r["project_id"] for r in rows]
    assert len(set(ids)) == len(ids)
    assert all(i.startswith("project_") for i in ids)
    again = ip.build_rows(REPO_ROOT)["project_rows"]
    assert [r["project_id"] for r in again] == ids
