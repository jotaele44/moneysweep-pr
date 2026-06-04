"""Tests for the top-form Agency Master producer (Gate 5, item ``agency_master``).

Fully offline: the producer reads only committed public reference CSVs and
validates against ``schemas/agency_master.schema.json`` via the stdlib
canonical_v1 schema interpreter (no ``jsonschema`` dependency).
"""
from __future__ import annotations

import csv
import json
import re
from pathlib import Path

import pytest

from contract_sweeper.runtime.canonical_ids import name_hash
from contract_sweeper.validation.canonical_v1_schema import validate_row
from scripts import build_agency_master as bam

REPO_ROOT = bam.REPO_ROOT


@pytest.fixture(scope="module")
def rows():
    return bam.build_rows(REPO_ROOT)


@pytest.fixture(scope="module")
def schema():
    return json.loads((REPO_ROOT / bam.SCHEMA).read_text(encoding="utf-8"))


@pytest.mark.unit
def test_check_passes(rows):
    assert bam.check(rows, REPO_ROOT) == []


@pytest.mark.unit
def test_every_row_validates_against_schema(rows, schema):
    for row in rows:
        assert validate_row(row, schema) == [], row


@pytest.mark.unit
def test_ids_unique_deterministic_and_match_pattern(rows, schema):
    ids = [r["agency_id"] for r in rows]
    assert len(set(ids)) == len(ids)
    pattern = schema["properties"]["agency_id"]["pattern"]
    assert all(re.fullmatch(pattern, i) for i in ids)
    # deterministic agency id from canonical_name
    prepa = next(r for r in rows if r["canonical_name"] == "Puerto Rico Electric Power Authority")
    assert prepa["agency_id"] == f"ENT_AGENCY_{name_hash('Puerto Rico Electric Power Authority')}"
    # deterministic municipio id from the stable FIPS-style code
    adjuntas = next(r for r in rows if r["canonical_name"] == "Adjuntas")
    assert adjuntas["agency_id"] == "ENT_MUNI_72001"


@pytest.mark.unit
def test_agency_types_within_schema_enum(rows, schema):
    enum = set(schema["properties"]["agency_type"]["enum"])
    assert {r["agency_type"] for r in rows} <= enum
    assert {r["agency_type"] for r in rows} == {"government_agency", "public_corporation", "municipality"}


@pytest.mark.unit
def test_evidence_tier_and_confidence(rows):
    for r in rows:
        assert r["evidence_tier"] in {"T1", "T2", "T3", "T4"}
        assert 0.0 <= float(r["confidence"]) <= 1.0


@pytest.mark.unit
def test_utility_maps_to_public_corporation(rows):
    prepa = next(r for r in rows if r["canonical_name"] == "Puerto Rico Electric Power Authority")
    assert prepa["agency_type"] == "public_corporation"
    prasa = next(r for r in rows if r["canonical_name"] == "Puerto Rico Aqueduct and Sewer Authority")
    assert prasa["agency_type"] == "public_corporation"


@pytest.mark.unit
def test_aliases_are_first_class(rows):
    # the normalization improvement over entity_master: aliases live in their own column
    adjuntas = next(r for r in rows if r["canonical_name"] == "Adjuntas")
    assert "ADJUNTAS" in adjuntas["aliases"]
    fomb = next(r for r in rows if r["canonical_name"].startswith("Financial Oversight"))
    assert "FOMB" in fomb["aliases"]


@pytest.mark.unit
def test_municipio_and_agency_counts(rows):
    munis = [r for r in rows if r["agency_type"] == "municipality"]
    govt = [r for r in rows if r["agency_type"] in {"government_agency", "public_corporation"}]
    assert len(munis) == 78
    assert len(govt) == 17
    assert len(rows) == 95
    # all municipio ids are FIPS-coded and distinct
    assert len({r["agency_id"] for r in munis}) == 78


@pytest.mark.integration
def test_regenerates_identically(rows):
    """The committed agency_master.csv must match a fresh build, row-for-row."""
    out_path = REPO_ROOT / bam.AGENCY_MASTER_OUT
    assert out_path.exists(), "agency_master.csv not written — run scripts/build_agency_master.py"
    with out_path.open(newline="", encoding="utf-8") as fh:
        committed = list(csv.DictReader(fh))
    assert len(committed) == len(rows)
    for built, on_disk in zip(rows, committed):
        assert on_disk["agency_id"] == built["agency_id"]
        assert on_disk["agency_type"] == built["agency_type"]
        assert on_disk["canonical_name"] == built["canonical_name"]
        assert on_disk["aliases"] == built["aliases"]
        assert float(on_disk["confidence"]) == float(built["confidence"])
