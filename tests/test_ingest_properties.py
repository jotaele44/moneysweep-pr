"""Tests for the canonical_v1 properties ingester (WS-K)."""

import pytest

from contract_sweeper.validation import canonical_v1_schema as cv1
from scripts import ingest_properties as ip

REPO_ROOT = cv1.REPO_ROOT


@pytest.fixture(scope="module")
def built():
    return ip.build_rows(REPO_ROOT)


@pytest.mark.integration
def test_seed_properties_resolve_owner_and_municipality(built):
    rows = built["property_rows"]
    assert len(rows) == 4
    assert built["skipped"] == []
    assert ip.check(rows) == []
    assert {r["property_type"] for r in rows} == {"concession", "facility"}


@pytest.mark.integration
def test_rows_and_evidence_validate(built):
    p_schema = cv1.load_schema("properties", REPO_ROOT)
    ev_schema = cv1.load_schema("evidence", REPO_ROOT)
    tables = cv1.load_all_tables(REPO_ROOT)
    entity_ids = {r["entity_id"] for r in tables["entities"]}
    muni_ids = {r["municipality_id"] for r in tables["municipalities"]}
    evidence_ids = {e.evidence_id for e in built["evidence_rows"]}
    for row in built["property_rows"]:
        assert cv1.validate_row(row, p_schema) == [], row
        assert row["owner_entity_id"] in entity_ids  # no broken reference
        assert row["municipality_id"] in muni_ids
        assert row["evidence_id"] in evidence_ids  # no provenance -> no row
    for ev in built["evidence_rows"]:
        assert cv1.validate_row(ev.as_row(), ev_schema) == [], ev


@pytest.mark.unit
def test_property_ids_unique_and_deterministic(built):
    rows = built["property_rows"]
    ids = [r["property_id"] for r in rows]
    assert len(set(ids)) == len(ids)
    assert all(i.startswith("property_") for i in ids)
    again = ip.build_rows(REPO_ROOT)["property_rows"]
    assert [r["property_id"] for r in again] == ids
