"""Tests for the top-form Entity Master producer (Gate 5, item ``entity_master``).

Fully offline: the producer reads only the committed public reference CSV and
validates against ``schemas/entity_master.schema.json`` via the stdlib
canonical_v1 schema interpreter (no ``jsonschema`` dependency).
"""

from __future__ import annotations

import csv
import json
import re

import pytest

from contract_sweeper.runtime.canonical_ids import name_hash
from contract_sweeper.validation.canonical_v1_schema import validate_row
from scripts import build_entity_master as bem

REPO_ROOT = bem.REPO_ROOT


@pytest.fixture(scope="module")
def rows():
    return bem.build_rows(REPO_ROOT)


@pytest.fixture(scope="module")
def schema():
    return json.loads((REPO_ROOT / bem.SCHEMA).read_text(encoding="utf-8"))


@pytest.mark.unit
def test_check_passes(rows):
    assert bem.check(rows, REPO_ROOT) == []


@pytest.mark.unit
def test_every_row_validates_against_schema(rows, schema):
    for row in rows:
        assert validate_row(row, schema) == [], row


@pytest.mark.unit
def test_ids_unique_deterministic_and_match_pattern(rows, schema):
    ids = [r["entity_id"] for r in rows]
    assert len(set(ids)) == len(ids)
    pattern = schema["properties"]["entity_id"]["pattern"]
    assert all(re.fullmatch(pattern, i) for i in ids)
    # deterministic from canonical_name + type code
    prepa = next(r for r in rows if r["canonical_name"] == "Puerto Rico Electric Power Authority")
    assert prepa["entity_id"] == f"ENT_AGENCY_{name_hash('Puerto Rico Electric Power Authority')}"


@pytest.mark.unit
def test_entity_types_within_schema_enum(rows, schema):
    enum = set(schema["properties"]["entity_type"]["enum"])
    assert {r["entity_type"] for r in rows} <= enum
    # the seed only yields these two buckets
    assert {r["entity_type"] for r in rows} == {"government_agency", "organization"}


@pytest.mark.unit
def test_evidence_tier_and_confidence(rows):
    for r in rows:
        assert r["evidence_tier"] in {"T1", "T2", "T3", "T4"}
        assert 0.0 <= float(r["confidence"]) <= 1.0


@pytest.mark.unit
def test_core_institutions_present(rows):
    names = {r["canonical_name"] for r in rows}
    for required in [
        "Puerto Rico Electric Power Authority",
        "Puerto Rico Aqueduct and Sewer Authority",
        "Financial Oversight and Management Board for Puerto Rico",
        "Puerto Rico Sales Tax Financing Corporation",
    ]:
        assert required in names
    assert len(rows) == 26


@pytest.mark.unit
def test_utility_maps_to_government_agency(rows):
    prepa = next(r for r in rows if r["canonical_name"] == "Puerto Rico Electric Power Authority")
    assert prepa["entity_type"] == "government_agency"


@pytest.mark.unit
def test_firm_maps_to_organization(rows):
    luma = next(r for r in rows if r["canonical_name"] == "LUMA Energy")
    assert luma["entity_type"] == "organization"
    assert luma["entity_id"].startswith("ENT_ORG_")


@pytest.mark.integration
def test_regenerates_identically(rows):
    """The committed entity_master.csv must match a fresh build, byte-for-byte rows."""
    out_path = REPO_ROOT / bem.ENTITY_MASTER_OUT
    assert out_path.exists(), "entity_master.csv not written — run scripts/build_entity_master.py"
    with out_path.open(newline="", encoding="utf-8") as fh:
        committed = list(csv.DictReader(fh))
    assert len(committed) == len(rows)
    for built, on_disk in zip(rows, committed):
        assert on_disk["entity_id"] == built["entity_id"]
        assert on_disk["entity_type"] == built["entity_type"]
        assert on_disk["canonical_name"] == built["canonical_name"]
        # confidence round-trips through CSV as a string
        assert float(on_disk["confidence"]) == float(built["confidence"])
