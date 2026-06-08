"""Tests for the top-form Influence Edges producer (Gate ``influence``).

Fully offline: the producer assembles canonical lobbying / role / parent-map
relationships into one influence-edge table and validates against
``schemas/influence_edges.schema.json`` via the stdlib canonical_v1 schema
interpreter (no ``jsonschema`` dependency).
"""

from __future__ import annotations

import csv
import json

import pytest

from contract_sweeper.validation.canonical_v1_schema import validate_row
from scripts import build_influence_edges as bie

REPO_ROOT = bie.REPO_ROOT


@pytest.fixture(scope="module")
def rows():
    return bie.build_rows(REPO_ROOT)


@pytest.fixture(scope="module")
def schema():
    return json.loads((REPO_ROOT / bie.SCHEMA).read_text(encoding="utf-8"))


@pytest.mark.unit
def test_check_passes(rows):
    assert bie.check(rows, REPO_ROOT) == []


@pytest.mark.unit
def test_row_count(rows):
    # 3 lobbying + 7 roles + 20 parent/operator relationships.
    assert len(rows) == 30


@pytest.mark.unit
def test_every_row_validates(rows, schema):
    for row in rows:
        assert validate_row(row, schema) == [], row


@pytest.mark.unit
def test_relationship_and_source_types_within_enum(rows, schema):
    rel_enum = set(schema["properties"]["relationship_type"]["enum"])
    src_enum = set(schema["properties"]["source_type"]["enum"])
    assert {r["relationship_type"] for r in rows} <= rel_enum
    assert {r["source_type"] for r in rows} <= src_enum


@pytest.mark.unit
def test_endpoints_resolve_to_masters(rows):
    types = bie._type_index(REPO_ROOT)
    for r in rows:
        assert r["from_entity_id"] in types
        assert r["to_entity_id"] in types
        assert r["from_entity_id"] != r["to_entity_id"]
        # declared entity types match the master index
        assert r["from_entity_type"] == types[r["from_entity_id"]]
        assert r["to_entity_type"] == types[r["to_entity_id"]]


@pytest.mark.unit
def test_relationship_mix(rows):
    by_rel: dict[str, int] = {}
    for r in rows:
        by_rel[r["relationship_type"]] = by_rel.get(r["relationship_type"], 0) + 1
    assert by_rel["LOBBIES_FOR"] == 3
    assert by_rel["BOARD_MEMBER_OF"] == 7
    assert by_rel["SUBSIDIARY_OF"] == 17  # the INSTRUMENTALITY_OF instrumentalities
    assert by_rel["OWNS_OR_CONTROLS"] == 3  # 2 P3 + 1 concession operators


@pytest.mark.unit
def test_operator_subtype_preserved(rows):
    owns = [r for r in rows if r["relationship_type"] == "OWNS_OR_CONTROLS"]
    assert owns
    for r in owns:
        assert r["relationship_subtype"] in ("P3_OPERATOR_OF", "CONCESSION_OPERATOR_OF")


@pytest.mark.unit
def test_every_edge_has_evidence(rows):
    for r in rows:
        assert r["evidence_tier"] in ("T1", "T2", "T3", "T4"), r
        assert 0.0 <= float(r["confidence"]) <= 1.0


@pytest.mark.integration
def test_regenerates_identically(rows):
    out_path = REPO_ROOT / bie.OUT
    assert out_path.exists(), (
        "influence_edges.csv not written — run scripts/build_influence_edges.py"
    )
    with out_path.open(newline="", encoding="utf-8") as fh:
        committed = list(csv.DictReader(fh))
    assert len(committed) == len(rows)
    for built, on_disk in zip(rows, committed):
        assert on_disk["edge_id"] == built["edge_id"]
        assert on_disk["relationship_type"] == built["relationship_type"]
        assert on_disk["from_entity_id"] == built["from_entity_id"]
        assert on_disk["to_entity_id"] == built["to_entity_id"]
