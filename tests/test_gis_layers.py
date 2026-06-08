"""Tests for the top-form GIS producers (Gate ``gis``).

Covers the four schema-locked gis artifacts — the 78-municipio crosswalk lock,
the geo-resolution vocabulary, the layer manifest, and the HQ-bias correction
contract. Fully offline; validation uses the stdlib canonical_v1 schema
interpreter (no ``jsonschema`` dependency).
"""

from __future__ import annotations

import csv
import json

import pytest

from contract_sweeper.validation.canonical_v1_schema import validate_row
from scripts import build_geo_reason_codes as bgr
from scripts import build_gis_layer_manifest as bgm
from scripts import build_hq_bias_reference as bhq
from scripts import build_municipality_crosswalk as bmc
from scripts.run_contract_finance_geo_reasoning import (
    GEO_RESOLUTION_REASONS,
    JURISDICTION_CLASSES,
    UNKNOWN_JURISDICTIONS,
)

REPO_ROOT = bmc.REPO_ROOT


def _schema(rel: str):
    return json.loads((REPO_ROOT / rel).read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
# municipality_crosswalk
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_crosswalk_locks_78_municipios():
    rows = bmc.build_rows(REPO_ROOT)
    assert bmc.check(rows, REPO_ROOT) == []
    assert len(rows) == 78
    schema = _schema(bmc.SCHEMA)
    for row in rows:
        assert validate_row(row, schema) == [], row
    geoids = [r["municipality_geoid"] for r in rows]
    assert len(set(geoids)) == 78
    assert all(g.startswith("72") and len(g) == 5 for g in geoids)
    # San Juan present (the HQ-bias reference municipio)
    assert "72127" in set(geoids)


# --------------------------------------------------------------------------- #
# geo_reason_codes
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_geo_reason_codes_match_resolver():
    rows = bgr.build_rows(REPO_ROOT)
    assert bgr.check(rows, REPO_ROOT) == []
    reasons = {r["code"] for r in rows if r["kind"] == "geo_resolution_reason"}
    jclasses = {r["code"] for r in rows if r["kind"] == "jurisdiction_class"}
    assert reasons == set(GEO_RESOLUTION_REASONS)
    assert jclasses == set(JURISDICTION_CLASSES)
    assert len(rows) == len(GEO_RESOLUTION_REASONS) + len(JURISDICTION_CLASSES)


@pytest.mark.unit
def test_geo_reason_codes_have_descriptions():
    schema = _schema(bgr.SCHEMA)
    for row in bgr.build_rows(REPO_ROOT):
        assert validate_row(row, schema) == [], row
        assert row["description"].strip()


# --------------------------------------------------------------------------- #
# layer_manifest
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_layer_manifest_valid():
    manifest = bgm.build_manifest(REPO_ROOT)
    assert bgm.check(manifest, REPO_ROOT) == []
    schema = _schema(bgm.SCHEMA)
    item_schema = schema["properties"]["layers"]["items"]
    for layer in manifest["layers"]:
        assert validate_row(layer, item_schema) == [], layer
    statuses = {layer["layer_id"]: layer["status"] for layer in manifest["layers"]}
    assert statuses["municipality_density"] == "done"
    assert statuses["project_points"] == "blocked"  # no coordinates committed


@pytest.mark.integration
def test_layer_manifest_written_and_matches():
    out = REPO_ROOT / bgm.OUT
    assert out.exists(), "layer_manifest.json not written — run scripts/build_gis_layer_manifest.py"
    on_disk = json.loads(out.read_text(encoding="utf-8"))
    built = bgm.build_manifest(REPO_ROOT)
    assert on_disk == built


# --------------------------------------------------------------------------- #
# hq_bias_correction
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_hq_bias_contract_locked_to_resolver():
    rows = bhq.build_rows(REPO_ROOT)
    assert bhq.check(rows, REPO_ROOT) == []
    by_aspect = {r["aspect"]: r["value"] for r in rows}
    # the correction must reference the resolver's real vocabulary
    assert by_aspect["reason_code"] == "headquarters_only"
    assert by_aspect["reason_code"] in GEO_RESOLUTION_REASONS
    assert by_aspect["jurisdiction_class"] == "HEADQUARTERS_ONLY"
    assert by_aspect["jurisdiction_class"] in JURISDICTION_CLASSES
    # HQ-only is counted as unknown, never as a place of performance
    assert "HEADQUARTERS_ONLY" in UNKNOWN_JURISDICTIONS
    # place of performance always precedes headquarters in the precedence chain
    order = by_aspect["place_precedence"].split(">")
    assert order.index("place_of_performance_exact") < order.index("headquarters_only")


@pytest.mark.integration
def test_gis_csv_outputs_regenerate_identically():
    for mod in (bgr, bhq):
        out = REPO_ROOT / mod.OUT
        assert out.exists(), f"{mod.OUT} not written"
        with out.open(newline="", encoding="utf-8") as fh:
            committed = list(csv.DictReader(fh))
        built = mod.build_rows(REPO_ROOT)
        assert len(committed) == len(built)
        for b, d in zip(built, committed):
            for col in mod.COLUMNS:
                assert str(b[col]) == d[col], (mod.OUT, col, b, d)
