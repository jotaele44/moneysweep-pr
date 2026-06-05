"""Tests for the top-form FOIA gate producers (Gate ``foia``).

Covers the FOIA priority queue (request tracker), the yield tracker, and the
request-templates doc. Fully offline; validation uses the stdlib canonical_v1
schema interpreter (no ``jsonschema`` dependency). Producers use ``build_rows``
(read-only) so the working tree is never touched.
"""
from __future__ import annotations

import csv
import json

import pytest

from contract_sweeper.validation.canonical_v1_schema import validate_row
from scripts import build_foia_tracker as bft
from scripts import build_foia_yield_tracking as bfy

REPO_ROOT = bft.REPO_ROOT


def _schema(rel: str):
    return json.loads((REPO_ROOT / rel).read_text(encoding="utf-8"))


def _committed(rel: str):
    with (REPO_ROOT / rel).open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


# --------------------------------------------------------------------------- #
# foia_tracker
# --------------------------------------------------------------------------- #

@pytest.fixture(scope="module")
def foia_rows():
    return bft.build_rows(REPO_ROOT)


@pytest.mark.unit
def test_foia_check_passes(foia_rows):
    assert bft.check(foia_rows, REPO_ROOT) == []


@pytest.mark.unit
def test_foia_rows_validate_and_are_unique(foia_rows):
    schema = _schema(bft.SCHEMA)
    assert foia_rows
    for row in foia_rows:
        assert validate_row(bft._public_row(row), schema) == [], row
    ids = [r["request_id"] for r in foia_rows]
    assert len(set(ids)) == len(ids)
    targets = [r["target_source_id"] for r in foia_rows]
    assert len(set(targets)) == len(targets)


@pytest.mark.unit
def test_foia_targets_are_real_unmet_gaps(foia_rows):
    status = bft._source_status_index(REPO_ROOT)
    for r in foia_rows:
        assert r["target_source_id"] in status, r["target_source_id"]
        assert status[r["target_source_id"]] != "fully_materialized"
    # statute matches jurisdiction
    for r in foia_rows:
        if r["jurisdiction"] == "US":
            assert "552" in r["statute"]
        else:
            assert "141" in r["statute"]


@pytest.mark.integration
def test_foia_regenerates_identically(foia_rows):
    committed = _committed(bft.OUT)
    assert len(committed) == len(foia_rows)
    for built, on_disk in zip(foia_rows, committed):
        assert on_disk["request_id"] == built["request_id"]
        assert on_disk["target_source_id"] == built["target_source_id"]


# --------------------------------------------------------------------------- #
# yield_tracking
# --------------------------------------------------------------------------- #

@pytest.fixture(scope="module")
def yield_rows():
    return bfy.build_rows(REPO_ROOT)


@pytest.mark.unit
def test_yield_check_passes(yield_rows):
    assert bfy.check(yield_rows, REPO_ROOT) == []


@pytest.mark.unit
def test_yield_one_row_per_request(yield_rows, foia_rows):
    schema = _schema(bfy.SCHEMA)
    for row in yield_rows:
        assert validate_row(row, schema) == [], row
    assert {r["request_id"] for r in yield_rows} == {r["request_id"] for r in foia_rows}
    # nothing fulfilled yet -> every gap is still open with a non-empty blocker
    for r in yield_rows:
        assert r["yield_status"] in ("pending", "partial", "no_response")
        assert r["unresolved_gap"].strip()
        assert int(r["records_received"]) == 0


@pytest.mark.integration
def test_yield_regenerates_identically(yield_rows):
    committed = _committed(bfy.OUT)
    assert len(committed) == len(yield_rows)
    for built, on_disk in zip(yield_rows, committed):
        assert on_disk["request_id"] == built["request_id"]
        assert on_disk["yield_status"] == built["yield_status"]


# --------------------------------------------------------------------------- #
# submission state
# --------------------------------------------------------------------------- #

@pytest.mark.unit
def test_foia_all_submitted(foia_rows):
    for r in foia_rows:
        assert r["request_status"] == "submitted", \
            f"{r['request_id']} expected submitted, got {r['request_status']}"



# --------------------------------------------------------------------------- #
# request_templates
# --------------------------------------------------------------------------- #

@pytest.mark.unit
def test_request_templates_doc_present_and_complete():
    doc = (REPO_ROOT / "docs/FOIA_REQUEST_TEMPLATES.md").read_text(encoding="utf-8")
    # both jurisdictions' statutes are documented
    assert "Ley 141-2019" in doc
    assert "5 U.S.C." in doc and "552" in doc
    # the templates reference the queue placeholders
    assert "{{target_agency}}" in doc
    assert "{{record_type}}" in doc
    assert "{{request_id}}" in doc
