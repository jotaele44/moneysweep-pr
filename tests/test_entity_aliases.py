"""Tests for the top-form Entity Aliases producer (Gate 5, item ``entity_aliases``).

Fully offline: the producer explodes aliases from the committed master tables and
validates against ``schemas/entity_aliases.schema.json`` via the stdlib
canonical_v1 schema interpreter (no ``jsonschema`` dependency).
"""

from __future__ import annotations

import csv
import json
import re

import pytest

from contract_sweeper.runtime.name_normalization import normalize_name
from contract_sweeper.validation.canonical_v1_schema import validate_row
from scripts import build_entity_aliases as bea

REPO_ROOT = bea.REPO_ROOT


@pytest.fixture(scope="module")
def rows():
    return bea.build_rows(REPO_ROOT)


@pytest.fixture(scope="module")
def schema():
    return json.loads((REPO_ROOT / bea.SCHEMA).read_text(encoding="utf-8"))


@pytest.mark.unit
def test_check_passes(rows):
    assert bea.check(rows, REPO_ROOT) == []


@pytest.mark.unit
def test_every_row_validates_against_schema(rows, schema):
    for row in rows:
        assert validate_row(row, schema) == [], row


@pytest.mark.unit
def test_ids_unique_and_match_pattern(rows, schema):
    ids = [r["alias_id"] for r in rows]
    assert len(set(ids)) == len(ids)
    pattern = schema["properties"]["alias_id"]["pattern"]
    assert all(re.fullmatch(pattern, i) for i in ids)


@pytest.mark.unit
def test_no_duplicate_alias_per_entity(rows):
    seen = {(r["entity_id"], r["normalized_alias"]) for r in rows}
    assert len(seen) == len(rows)


@pytest.mark.unit
def test_normalized_alias_is_consistent(rows):
    for r in rows:
        assert r["normalized_alias"] == normalize_name(r["alias"])


@pytest.mark.unit
def test_referential_integrity(rows):
    known = bea._master_entity_ids(REPO_ROOT)
    assert all(r["entity_id"] in known for r in rows)


@pytest.mark.unit
def test_known_aliases_present(rows):
    # PREPA's alternates resolve to its agency master id
    prepa_aliases = {r["alias"] for r in rows if r["entity_id"] == "ENT_AGENCY_6c1d858c1babe390"}
    assert {"PREPA", "AEE"} <= prepa_aliases
    # municipios contribute aliases too
    assert any(r["entity_id"].startswith("ENT_MUNI_") for r in rows)


@pytest.mark.integration
def test_regenerates_identically(rows):
    out_path = REPO_ROOT / bea.ENTITY_ALIASES_OUT
    assert out_path.exists(), "entity_aliases.csv not written — run scripts/build_entity_aliases.py"
    with out_path.open(newline="", encoding="utf-8") as fh:
        committed = list(csv.DictReader(fh))
    assert len(committed) == len(rows)
    for built, on_disk in zip(rows, committed):
        assert on_disk["alias_id"] == built["alias_id"]
        assert on_disk["entity_id"] == built["entity_id"]
        assert on_disk["alias"] == built["alias"]
