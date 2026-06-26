"""Tests for the Entity Resolution Review Queue producer (Gate 5, item ``review_queue``).

Fully offline: the producer surfaces low-confidence master rows and validates
against the existing ``schemas/canonical_v1/review_queue.schema.json`` via the
stdlib canonical_v1 schema interpreter (no ``jsonschema`` dependency).
"""

from __future__ import annotations

import csv
import json
import re

import pytest

from moneysweep.validation.canonical_v1_schema import validate_row
from scripts import build_entity_resolution_review_queue as brq

REPO_ROOT = brq.REPO_ROOT


@pytest.fixture(scope="module")
def rows():
    return brq.build_rows(REPO_ROOT)


@pytest.fixture(scope="module")
def schema():
    return json.loads((REPO_ROOT / brq.SCHEMA).read_text(encoding="utf-8"))


@pytest.mark.unit
def test_check_passes(rows):
    assert brq.check(rows, REPO_ROOT) == []


@pytest.mark.unit
def test_every_row_validates_against_schema(rows, schema):
    for row in rows:
        assert validate_row(row, schema) == [], row


@pytest.mark.unit
def test_ids_unique_and_match_pattern(rows, schema):
    ids = [r["review_id"] for r in rows]
    assert len(set(ids)) == len(ids)
    pattern = schema["properties"]["review_id"]["pattern"]
    assert all(re.fullmatch(pattern, i) for i in ids)


@pytest.mark.unit
def test_issue_type_and_status_within_enum(rows, schema):
    issue_enum = set(schema["properties"]["issue_type"]["enum"])
    status_enum = set(schema["properties"]["status"]["enum"])
    severity_enum = set(schema["properties"]["severity"]["enum"])
    for r in rows:
        assert r["issue_type"] in issue_enum
        assert r["status"] in status_enum
        assert r["severity"] in severity_enum


@pytest.mark.unit
def test_only_low_confidence_surfaced(rows):
    # every queued person must be below the threshold in the person master
    conf = {}
    with (REPO_ROOT / brq.PERSON_MASTER).open(newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            conf[r["person_id"]] = float(r["confidence"])
    assert rows  # non-empty
    for r in rows:
        assert conf[r["object_id"]] < brq.CONFIDENCE_THRESHOLD
    # and the count matches the master's below-threshold population
    expected = sum(1 for v in conf.values() if v < brq.CONFIDENCE_THRESHOLD)
    assert len(rows) == expected == 24


@pytest.mark.unit
def test_referential_integrity(rows):
    known = set()
    with (REPO_ROOT / brq.PERSON_MASTER).open(newline="", encoding="utf-8") as fh:
        known.update(r["person_id"] for r in csv.DictReader(fh))
    assert all(r["object_id"] in known for r in rows)


@pytest.mark.integration
def test_regenerates_identically(rows):
    out_path = REPO_ROOT / brq.REVIEW_QUEUE_OUT
    assert out_path.exists(), (
        "review queue not written — run scripts/build_entity_resolution_review_queue.py"
    )
    with out_path.open(newline="", encoding="utf-8") as fh:
        committed = list(csv.DictReader(fh))
    assert len(committed) == len(rows)
    for built, on_disk in zip(rows, committed):
        assert on_disk["review_id"] == built["review_id"]
        assert on_disk["object_id"] == built["object_id"]
        assert on_disk["issue_type"] == built["issue_type"]
