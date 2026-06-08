"""Tests for the top-form Person Master producer (Gate 5, item ``person_master``).

Fully offline: the producer reads only the committed canonical_v1 people table and
validates against ``schemas/person_master.schema.json`` via the stdlib
canonical_v1 schema interpreter (no ``jsonschema`` dependency).
"""
from __future__ import annotations

import csv
import json
import re

import pytest

from contract_sweeper.validation.canonical_v1_schema import validate_row
from scripts import build_person_master as bpm

REPO_ROOT = bpm.REPO_ROOT


@pytest.fixture(scope="module")
def rows():
    return bpm.build_rows(REPO_ROOT)


@pytest.fixture(scope="module")
def schema():
    return json.loads((REPO_ROOT / bpm.SCHEMA).read_text(encoding="utf-8"))


@pytest.mark.unit
def test_check_passes(rows):
    assert bpm.check(rows, REPO_ROOT) == []


@pytest.mark.unit
def test_every_row_validates_against_schema(rows, schema):
    for row in rows:
        assert validate_row(row, schema) == [], row


@pytest.mark.unit
def test_ids_unique_deterministic_and_match_pattern(rows, schema):
    ids = [r["person_id"] for r in rows]
    assert len(set(ids)) == len(ids)
    pattern = schema["properties"]["person_id"]["pattern"]
    assert all(re.fullmatch(pattern, i) for i in ids)
    # deterministic: person_id reuses the stable canonical_v1 per-person suffix
    for r in rows:
        assert r["person_id"] == "ENT_PERSON_" + r["source_person_id"].removeprefix("person_")


@pytest.mark.unit
def test_evidence_tier_and_confidence(rows):
    for r in rows:
        assert r["evidence_tier"] in {"T1", "T2", "T3", "T4"}
        assert 0.0 <= float(r["confidence"]) <= 1.0


@pytest.mark.unit
def test_source_provenance_carried(rows):
    for r in rows:
        assert r["source_id"] == "canonical_v1_people"
        assert r["source_person_id"].startswith("person_")
        assert r["person_id"].startswith("ENT_PERSON_")


@pytest.mark.unit
def test_known_people_present(rows):
    names = {r["canonical_name"] for r in rows}
    # a FOMB board member and a well-known official should be in the registry
    assert "Andrew Biggs" in names
    assert any("García Padilla" in n for n in names)
    assert len(rows) == 60


@pytest.mark.integration
def test_regenerates_identically(rows):
    """The committed person_master.csv must match a fresh build, row-for-row."""
    out_path = REPO_ROOT / bpm.PERSON_MASTER_OUT
    assert out_path.exists(), "person_master.csv not written — run scripts/build_person_master.py"
    with out_path.open(newline="", encoding="utf-8") as fh:
        committed = list(csv.DictReader(fh))
    assert len(committed) == len(rows)
    for built, on_disk in zip(rows, committed):
        assert on_disk["person_id"] == built["person_id"]
        assert on_disk["canonical_name"] == built["canonical_name"]
        assert on_disk["source_person_id"] == built["source_person_id"]
        assert float(on_disk["confidence"]) == float(built["confidence"])
