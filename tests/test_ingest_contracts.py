"""Tests for the canonical_v1 contracts ingester (WS-F)."""
import pytest

from contract_sweeper.validation import canonical_v1_schema as cv1
from scripts import ingest_contracts as ic

REPO_ROOT = cv1.REPO_ROOT


@pytest.fixture(scope="module")
def built():
    return ic.build_rows(REPO_ROOT)


@pytest.mark.integration
def test_seed_contracts_resolve_awarding_entities(built):
    rows = built["contract_rows"]
    assert len(rows) == 3
    assert built["skipped"] == []
    assert ic.check(rows) == []
    assert all(r["status"] == "active" for r in rows)


@pytest.mark.integration
def test_rows_and_evidence_validate(built):
    c_schema = cv1.load_schema("contracts", REPO_ROOT)
    ev_schema = cv1.load_schema("evidence", REPO_ROOT)
    tables = cv1.load_all_tables(REPO_ROOT)
    entity_ids = {r["entity_id"] for r in tables["entities"]}
    project_ids = {r["project_id"] for r in tables["projects"]}
    evidence_ids = {e.evidence_id for e in built["evidence_rows"]}
    for row in built["contract_rows"]:
        assert cv1.validate_row(row, c_schema) == [], row
        assert row["awarding_entity_id"] in entity_ids       # no broken reference
        assert row["contractor_entity_id"] in entity_ids
        assert row["project_id"] in project_ids
        assert row["evidence_id"] in evidence_ids            # no provenance -> no row
        assert row["currency"] == "USD"
    for ev in built["evidence_rows"]:
        assert cv1.validate_row(ev.as_row(), ev_schema) == [], ev


@pytest.mark.unit
def test_contract_ids_unique_and_deterministic(built):
    rows = built["contract_rows"]
    ids = [r["contract_id"] for r in rows]
    assert len(set(ids)) == len(ids)
    assert all(i.startswith("contract_") for i in ids)
    again = ic.build_rows(REPO_ROOT)["contract_rows"]
    assert [r["contract_id"] for r in again] == ids
