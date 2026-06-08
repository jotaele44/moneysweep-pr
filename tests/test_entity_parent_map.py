"""Tests for the top-form Entity Parent Map producer (Gate 5, item ``parent_map``).

Fully offline: the producer resolves a curated seed against the committed
entity master and validates against ``schemas/entity_parent_map.schema.json`` via
the stdlib canonical_v1 schema interpreter (no ``jsonschema`` dependency).
"""

from __future__ import annotations

import csv
import json
import re

import pytest

from contract_sweeper.validation.canonical_v1_schema import validate_row
from scripts import build_entity_parent_map as bpm

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
        assert validate_row(bpm._public_row(row), schema) == [], row


@pytest.mark.unit
def test_ids_unique_and_match_pattern(rows, schema):
    ids = [r["relation_id"] for r in rows]
    assert len(set(ids)) == len(ids)
    pattern = schema["properties"]["relation_id"]["pattern"]
    assert all(re.fullmatch(pattern, i) for i in ids)


@pytest.mark.unit
def test_relationship_types_within_enum(rows, schema):
    enum = set(schema["properties"]["relationship_type"]["enum"])
    assert {r["relationship_type"] for r in rows} <= enum


@pytest.mark.unit
def test_all_ids_resolved_and_no_self_reference(rows):
    for r in rows:
        assert r["parent_entity_id"].startswith("ENT_")
        assert r["child_entity_id"].startswith("ENT_")
        assert r["parent_entity_id"] != r["child_entity_id"]


@pytest.mark.unit
def test_referential_integrity(rows):
    index = bpm._name_index(REPO_ROOT)
    known = set(index.values())
    for r in rows:
        assert r["parent_entity_id"] in known
        assert r["child_entity_id"] in known


@pytest.mark.unit
def test_expected_relationships(rows):
    index = bpm._name_index(REPO_ROOT)
    prepa = index["Puerto Rico Electric Power Authority"]
    luma = index["LUMA Energy"]
    commonwealth = index["Commonwealth of Puerto Rico"]
    # LUMA operates PREPA assets under P3
    luma_rel = next(r for r in rows if r["child_entity_id"] == luma)
    assert luma_rel["parent_entity_id"] == prepa
    assert luma_rel["relationship_type"] == "P3_OPERATOR_OF"
    # PREPA is an instrumentality of the Commonwealth
    prepa_rel = next(r for r in rows if r["child_entity_id"] == prepa)
    assert prepa_rel["parent_entity_id"] == commonwealth
    assert prepa_rel["relationship_type"] == "INSTRUMENTALITY_OF"
    assert len(rows) == 20


@pytest.mark.integration
def test_regenerates_identically(rows):
    out_path = REPO_ROOT / bpm.PARENT_MAP_OUT
    assert out_path.exists(), (
        "entity_parent_map.csv not written — run scripts/build_entity_parent_map.py"
    )
    with out_path.open(newline="", encoding="utf-8") as fh:
        committed = list(csv.DictReader(fh))
    assert len(committed) == len(rows)
    for built, on_disk in zip(rows, committed):
        assert on_disk["relation_id"] == built["relation_id"]
        assert on_disk["parent_entity_id"] == built["parent_entity_id"]
        assert on_disk["child_entity_id"] == built["child_entity_id"]
        assert on_disk["relationship_type"] == built["relationship_type"]
