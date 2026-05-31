"""Tests for the canonical_v1 entities seed ingester (WS-E)."""
import pytest

from contract_sweeper.runtime.canonical_ids import entity_id
from contract_sweeper.validation import canonical_v1_schema as cv1
from scripts import ingest_entities as ie

REPO_ROOT = cv1.REPO_ROOT


@pytest.fixture(scope="module")
def built():
    rows, evidence = ie.build_rows(REPO_ROOT)
    return rows, evidence


@pytest.mark.integration
def test_seed_has_core_institutions(built):
    rows, _ = built
    names = {r["name"] for r in rows}
    for required in [
        "Puerto Rico Electric Power Authority",
        "Puerto Rico Aqueduct and Sewer Authority",
        "Puerto Rico Sales Tax Financing Corporation",
        "Financial Oversight and Management Board for Puerto Rico",
    ]:
        assert required in names
    assert ie.check(rows) == []


@pytest.mark.integration
def test_rows_and_evidence_validate(built):
    rows, evidence = built
    ent_schema = cv1.load_schema("entities", REPO_ROOT)
    ev_schema = cv1.load_schema("evidence", REPO_ROOT)
    evidence_ids = {e.evidence_id for e in evidence}
    for row in rows:
        assert cv1.validate_row(row, ent_schema) == [], row
        assert row["evidence_id"] in evidence_ids
    for ev in evidence:
        assert cv1.validate_row(ev.as_row(), ev_schema) == [], ev


@pytest.mark.unit
def test_entity_ids_unique_and_deterministic(built):
    rows, _ = built
    ids = [r["entity_id"] for r in rows]
    assert len(set(ids)) == len(ids)
    assert all(i.startswith("entity_") for i in ids)
    # deterministic from name
    prepa = next(r for r in rows if r["name"] == "Puerto Rico Electric Power Authority")
    assert prepa["entity_id"] == entity_id("Puerto Rico Electric Power Authority")


@pytest.mark.unit
def test_entity_types_are_in_enum(built):
    rows, _ = built
    assert {r["entity_type"] for r in rows} <= ie.VALID_TYPES
