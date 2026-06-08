"""Tests for the canonical_v1 lobbying ingester (WS-H)."""

import pytest

from contract_sweeper.validation import canonical_v1_schema as cv1
from scripts import ingest_lobbying as il

REPO_ROOT = cv1.REPO_ROOT


@pytest.fixture(scope="module")
def built():
    return il.build_rows(REPO_ROOT)


@pytest.mark.integration
def test_seed_lobbying_records_resolve_firm_and_client(built):
    rows = built["lobbying_rows"]
    assert len(rows) == 3
    assert built["skipped"] == []
    assert il.check(rows) == []
    assert all(r["jurisdiction"] == "PR" for r in rows)
    assert all(r["filing_type"] == "PR_cabildero" for r in rows)


@pytest.mark.integration
def test_rows_and_evidence_validate(built):
    lob_schema = cv1.load_schema("lobbying_records", REPO_ROOT)
    ev_schema = cv1.load_schema("evidence", REPO_ROOT)
    entity_ids = {r["entity_id"] for r in cv1.load_all_tables(REPO_ROOT)["entities"]}
    evidence_ids = {e.evidence_id for e in built["evidence_rows"]}
    for row in built["lobbying_rows"]:
        assert cv1.validate_row(row, lob_schema) == [], row
        assert row["lobbyist_entity_id"] in entity_ids  # no broken reference
        assert row["client_entity_id"] in entity_ids
        assert row["evidence_id"] in evidence_ids  # no provenance -> no row
    for ev in built["evidence_rows"]:
        assert cv1.validate_row(ev.as_row(), ev_schema) == [], ev


@pytest.mark.unit
def test_lobbying_ids_unique_and_deterministic(built):
    rows = built["lobbying_rows"]
    ids = [r["lobbying_record_id"] for r in rows]
    assert len(set(ids)) == len(ids)
    assert all(i.startswith("lobby_") for i in ids)
    again = il.build_rows(REPO_ROOT)["lobbying_rows"]
    assert [r["lobbying_record_id"] for r in again] == ids
