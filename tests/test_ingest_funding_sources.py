"""Tests for the canonical_v1 funding-sources ingester (WS-I)."""

import pytest

from contract_sweeper.runtime.canonical_ids import funding_id
from contract_sweeper.validation import canonical_v1_schema as cv1
from scripts import ingest_funding_sources as ifs

REPO_ROOT = cv1.REPO_ROOT


@pytest.fixture(scope="module")
def built():
    return ifs.build_rows(REPO_ROOT)


@pytest.mark.integration
def test_seed_funding_programs(built):
    rows = built["funding_rows"]
    assert len(rows) == 4
    assert built["skipped"] == []
    assert ifs.check(rows) == []
    assert {r["program"] for r in rows} == {"FEMA", "CDBG-DR", "EPA", "DOE"}


@pytest.mark.integration
def test_rows_and_evidence_validate(built):
    fs_schema = cv1.load_schema("funding_sources", REPO_ROOT)
    ev_schema = cv1.load_schema("evidence", REPO_ROOT)
    evidence_ids = {e.evidence_id for e in built["evidence_rows"]}
    for row in built["funding_rows"]:
        assert cv1.validate_row(row, fs_schema) == [], row
        assert row["evidence_id"] in evidence_ids  # no provenance -> no row
        assert row["currency"] == "USD"
    for ev in built["evidence_rows"]:
        assert cv1.validate_row(ev.as_row(), ev_schema) == [], ev


@pytest.mark.unit
def test_funding_ids_unique_and_deterministic(built):
    rows = built["funding_rows"]
    ids = [r["funding_source_id"] for r in rows]
    assert len(set(ids)) == len(ids)
    assert all(i.startswith("funding_") for i in ids)
    fema = next(r for r in rows if r["program"] == "FEMA")
    assert fema["funding_source_id"] == funding_id("FEMA", fema["program_year"])
