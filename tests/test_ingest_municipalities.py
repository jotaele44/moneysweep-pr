"""Tests for the canonical_v1 municipalities ingester (WS-K)."""
import pytest

from contract_sweeper.validation import canonical_v1_schema as cv1
from scripts import ingest_municipalities as im

REPO_ROOT = cv1.REPO_ROOT


@pytest.mark.integration
def test_build_rows_covers_all_78_municipalities():
    muni_rows, evidence_rows = im.build_rows(REPO_ROOT)
    assert len(muni_rows) == im.EXPECTED_COUNT == 78
    assert len(evidence_rows) == 78
    assert im.check_coverage(muni_rows) == []


@pytest.mark.integration
def test_rows_validate_against_schema_and_evidence_resolves():
    muni_rows, evidence_rows = im.build_rows(REPO_ROOT)
    muni_schema = cv1.load_schema("municipalities", REPO_ROOT)
    ev_schema = cv1.load_schema("evidence", REPO_ROOT)
    evidence_ids = {e.evidence_id for e in evidence_rows}

    for row in muni_rows:
        assert cv1.validate_row(row, muni_schema) == [], row
        assert row["evidence_id"] in evidence_ids  # no provenance -> no row

    for ev in evidence_rows:
        assert cv1.validate_row(ev.as_row(), ev_schema) == [], ev


@pytest.mark.unit
def test_municipality_ids_unique_and_well_formed():
    muni_rows, _ = im.build_rows(REPO_ROOT)
    ids = [r["municipality_id"] for r in muni_rows]
    assert len(set(ids)) == len(ids)
    assert all(i.startswith("muni_pr_") for i in ids)


@pytest.mark.unit
def test_build_rows_is_idempotent():
    first, _ = im.build_rows(REPO_ROOT)
    second, _ = im.build_rows(REPO_ROOT)
    assert [r["municipality_id"] for r in first] == [r["municipality_id"] for r in second]


@pytest.mark.unit
def test_check_coverage_flags_shortfall():
    rows = [{"municipality_id": "muni_pr_x", "county_fips": "72001"}]
    problems = im.check_coverage(rows)
    assert any("expected 78" in p for p in problems)
