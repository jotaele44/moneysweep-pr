"""Tests for the top-form debt_fiscal producers (Gate ``debt_fiscal``).

Covers the three schema-locked producers — debt instruments, creditor mapping,
and the fiscal-control-events timeline. Fully offline; validation uses the
stdlib canonical_v1 schema interpreter (no ``jsonschema`` dependency).
"""

from __future__ import annotations

import csv
import json

import pytest

from moneysweep.validation.canonical_v1_schema import validate_row
from scripts import build_creditor_mapping as bcm
from scripts import build_debt_instruments as bdi
from scripts import build_fiscal_control_events as bfe

REPO_ROOT = bdi.REPO_ROOT


def _schema(rel: str):
    return json.loads((REPO_ROOT / rel).read_text(encoding="utf-8"))


def _committed(rel: str):
    with (REPO_ROOT / rel).open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


# --------------------------------------------------------------------------- #
# debt_instruments
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def debt_rows():
    return bdi.build_rows(REPO_ROOT)


@pytest.mark.unit
def test_debt_check_passes(debt_rows):
    assert bdi.check(debt_rows, REPO_ROOT) == []


@pytest.mark.unit
def test_debt_count_and_schema(debt_rows):
    assert len(debt_rows) == 20
    schema = _schema(bdi.SCHEMA)
    for row in debt_rows:
        assert validate_row(bdi._public_row(row), schema) == [], row


@pytest.mark.unit
def test_debt_issuers_resolved(debt_rows):
    for r in debt_rows:
        assert r["issuer_entity_id"].startswith("ENT_")
        assert r["issuer_name"]
    classes = {r["debt_class"] for r in debt_rows}
    assert {"GO", "COFINA", "PREPA", "PRASA", "HTA"} <= classes


@pytest.mark.integration
def test_debt_regenerates_identically(debt_rows):
    committed = _committed(bdi.OUT)
    assert len(committed) == len(debt_rows)
    for built, on_disk in zip(debt_rows, committed):
        assert on_disk["debt_id"] == built["debt_id"]
        assert on_disk["issuer_entity_id"] == built["issuer_entity_id"]


# --------------------------------------------------------------------------- #
# creditor_mapping
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def creditor_rows():
    return bcm.build_rows(REPO_ROOT)


@pytest.mark.unit
def test_creditor_check_passes(creditor_rows):
    assert bcm.check(creditor_rows, REPO_ROOT) == []


@pytest.mark.unit
def test_creditor_aggregates(creditor_rows, debt_rows):
    schema = _schema(bcm.SCHEMA)
    for row in creditor_rows:
        assert validate_row(row, schema) == [], row
    # one row per distinct issuer; counts + par reconcile with debt_instruments
    assert len(creditor_rows) == len({r["issuer_entity_id"] for r in debt_rows})
    assert sum(r["instrument_count"] for r in creditor_rows) == len(debt_rows)
    total_par = sum(float(r["par_amount"]) for r in debt_rows if r["par_amount"] != "")
    assert abs(sum(r["total_par"] for r in creditor_rows) - total_par) < 1.0
    # sorted by total_par descending
    pars = [r["total_par"] for r in creditor_rows]
    assert pars == sorted(pars, reverse=True)


@pytest.mark.integration
def test_creditor_regenerates_identically(creditor_rows):
    committed = _committed(bcm.OUT)
    assert len(committed) == len(creditor_rows)
    for built, on_disk in zip(creditor_rows, committed):
        assert on_disk["issuer_entity_id"] == built["issuer_entity_id"]
        assert int(on_disk["instrument_count"]) == built["instrument_count"]


# --------------------------------------------------------------------------- #
# fiscal_control_events
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def event_rows():
    return bfe.build_rows(REPO_ROOT)


@pytest.mark.unit
def test_events_check_passes(event_rows):
    assert bfe.check(event_rows, REPO_ROOT) == []


@pytest.mark.unit
def test_events_schema_and_ids(event_rows):
    schema = _schema(bfe.SCHEMA)
    import re

    pattern = schema["properties"]["event_id"]["pattern"]
    ids = [r["event_id"] for r in event_rows]
    assert len(set(ids)) == len(ids)
    for row in event_rows:
        assert re.fullmatch(pattern, row["event_id"])
        assert validate_row(bfe._public_row(row), schema) == [], row


@pytest.mark.unit
def test_events_named_entities_resolve(event_rows):
    for r in event_rows:
        # a named related_entity must resolve to a master id
        if r["related_entity_name"]:
            assert r["related_entity_id"].startswith("ENT_"), r
    # PROMESA is a federal law with no single related entity -> blank id allowed
    promesa = next(r for r in event_rows if r["title"] == "PROMESA enacted")
    assert promesa["related_entity_id"] == ""
    assert promesa["event_type"] == "legislation"


@pytest.mark.unit
def test_events_chronological_coverage(event_rows):
    dates = [r["event_date"] for r in event_rows]
    assert dates == sorted(dates)  # seed is chronological
    assert any(r["event_type"] == "title_iii_filing" for r in event_rows)
    assert any(r["event_type"] == "plan_of_adjustment" for r in event_rows)


@pytest.mark.integration
def test_events_regenerates_identically(event_rows):
    committed = _committed(bfe.OUT)
    assert len(committed) == len(event_rows)
    for built, on_disk in zip(event_rows, committed):
        assert on_disk["event_id"] == built["event_id"]
        assert on_disk["title"] == built["title"]
