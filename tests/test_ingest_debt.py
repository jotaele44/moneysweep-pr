"""Tests for the canonical_v1 debt ingester (WS-J)."""

import pytest

from moneysweep.validation import canonical_v1_schema as cv1
from scripts import ingest_debt as idebt

REPO_ROOT = cv1.REPO_ROOT


@pytest.fixture(scope="module")
def built():
    return idebt.build_rows(REPO_ROOT)


@pytest.mark.unit
def test_classify_maps_issuers_to_enum():
    assert idebt.classify("COMMONWEALTH OF PUERTO RICO", "GO Bonds Series 2022A") == "GO"
    assert idebt.classify("PUERTO RICO SALES TAX FINANCING CORP", "COFINA Senior Bonds") == "COFINA"
    assert idebt.classify("PUERTO RICO ELECTRIC POWER AUTHORITY", "PREPA Power Revenue") == "PREPA"
    assert idebt.classify("PUERTO RICO AQUEDUCT AND SEWER AUTHORITY", "PRASA Revenue") == "PRASA"
    assert (
        idebt.classify("PUERTO RICO HIGHWAYS AND TRANSPORTATION AUTHORITY", "HTA Revenue") == "HTA"
    )
    assert idebt.classify("UNIVERSITY OF PUERTO RICO", "UPR System Revenue") == "other"


@pytest.mark.integration
def test_all_bonds_resolve_to_canonical_issuers(built):
    rows = built["debt_rows"]
    # all 20 KNOWN_EMMA_BONDS issuers now exist as canonical entities
    assert len(rows) == 20
    assert len(built["skipped"]) == 0
    assert idebt.check(rows) == []
    # the 5 primary classes plus 'other' for the remaining instrumentalities
    assert {r["debt_class"] for r in rows} == {"GO", "COFINA", "HTA", "PREPA", "PRASA", "other"}


@pytest.mark.integration
def test_rows_and_evidence_validate(built):
    debt_schema = cv1.load_schema("debt_instruments", REPO_ROOT)
    ev_schema = cv1.load_schema("evidence", REPO_ROOT)
    entity_ids = {r["entity_id"] for r in cv1.load_all_tables(REPO_ROOT)["entities"]}
    evidence_ids = {e.evidence_id for e in built["evidence_rows"]}
    for row in built["debt_rows"]:
        assert cv1.validate_row(row, debt_schema) == [], row
        assert row["issuer_entity_id"] in entity_ids  # no broken reference
        assert row["evidence_id"] in evidence_ids  # no provenance -> no row
        assert row["currency"] == "USD"
    for ev in built["evidence_rows"]:
        assert cv1.validate_row(ev.as_row(), ev_schema) == [], ev


@pytest.mark.unit
def test_debt_ids_unique_and_deterministic(built):
    rows = built["debt_rows"]
    ids = [r["debt_id"] for r in rows]
    assert len(set(ids)) == len(ids)
    assert all(i.startswith("debt_") for i in ids)
    # re-running yields identical ids
    again = idebt.build_rows(REPO_ROOT)["debt_rows"]
    assert [r["debt_id"] for r in again] == ids
