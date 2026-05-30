"""Tests for the Top250 people ingester (WS-D), using a synthetic fixture only."""
from pathlib import Path

import pytest

from contract_sweeper.validation import canonical_v1_schema as cv1
from scripts import ingest_people as ip

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "canonical_v1_people_sample.csv"


@pytest.fixture(scope="module")
def built():
    return ip.build_records(FIXTURE)


@pytest.mark.unit
def test_only_confirmed_high_tier_are_accepted(built):
    accepted = {r["full_name"] for r in built["people_rows"]}
    # Alice (confirmed T1), Eve (confirmed T1), and both Frank spellings (confirmed T1)
    assert accepted == {"Alice Verified", "Eve Multi", "Frank Smith", "Frank A Smith"}
    assert built["counts"]["verified_accepted"] == 4


@pytest.mark.unit
def test_unverified_and_ambiguous_are_queued_not_accepted(built):
    pending = {r["raw_value"]: r["issue_type"] for r in built["pending_rows"]}
    assert pending["Bob Pending"] == "unverified"          # confirmed=False
    assert pending["Carol Lowtier"] == "low_confidence"     # confirmed but Tier T3
    assert pending["Firm Co (Dan Embedded)"] == "ambiguous"  # firm-embedded name
    # none of the queued names leaked into the accepted node set
    accepted = {r["full_name"] for r in built["people_rows"]}
    assert accepted.isdisjoint({"Bob Pending", "Carol Lowtier", "Firm Co (Dan Embedded)"})


@pytest.mark.unit
def test_duplicate_rows_collapse_and_flows_union(built):
    eve = [r for r in built["people_rows"] if r["full_name"] == "Eve Multi"]
    assert len(eve) == 1
    assert "Contracts" in eve[0]["notes"] and "Debt" in eve[0]["notes"]


@pytest.mark.unit
def test_merge_candidates_flagged_for_similar_names(built):
    merges = [r for r in built["pending_rows"] if r["issue_type"] == "ambiguous_merge"]
    flagged = {r["raw_value"] for r in merges}
    assert {"Frank Smith", "Frank A Smith"} <= flagged


@pytest.mark.integration
def test_accepted_rows_and_evidence_validate(built):
    people_schema = cv1.load_schema("people", cv1.REPO_ROOT)
    ev_schema = cv1.load_schema("evidence", cv1.REPO_ROOT)
    evidence_ids = {e.evidence_id for e in built["evidence_rows"]}
    for row in built["people_rows"]:
        assert cv1.validate_row(row, people_schema) == [], row
        assert row["evidence_id"] in evidence_ids          # no provenance -> no row
    for ev in built["evidence_rows"]:
        assert cv1.validate_row(ev.as_row(), ev_schema) == [], ev


@pytest.mark.integration
def test_pending_rows_validate_against_review_queue_schema(built):
    rq_schema = cv1.load_schema("review_queue", cv1.REPO_ROOT)
    for row in built["pending_rows"]:
        assert cv1.validate_row(row, rq_schema) == [], row
