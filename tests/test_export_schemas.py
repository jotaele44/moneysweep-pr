"""On-disk export schema validation (Gate ``testing``, items ``graph_export_tests``
and ``gis_export_tests``).

Validates the committed export artifacts — the graph node/edge tables and the
GIS layer manifest — against their JSON schemas, independently of the producers
that wrote them. This is the consumer-side guard: whatever is on disk must
satisfy the published contract. Fully offline.
"""

from __future__ import annotations

import csv
import json

import pytest

from moneysweep.validation.canonical_v1_schema import validate_row
from scripts import build_graph_export as bge
from scripts import build_gis_layer_manifest as bgm

REPO_ROOT = bge.REPO_ROOT


def _schema(rel: str):
    return json.loads((REPO_ROOT / rel).read_text(encoding="utf-8"))


def _read_csv(rel: str):
    with (REPO_ROOT / rel).open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


# --------------------------------------------------------------------------- #
# graph_export
# --------------------------------------------------------------------------- #


@pytest.mark.integration
def test_graph_nodes_on_disk_validate():
    schema = _schema(bge.NODE_SCHEMA)
    rows = _read_csv(bge.NODES_OUT)
    assert rows
    for row in rows:
        assert validate_row(row, schema) == [], row


@pytest.mark.integration
def test_graph_edges_on_disk_validate_and_resolve():
    schema = _schema(bge.EDGE_SCHEMA)
    nodes = {r["node_id"] for r in _read_csv(bge.NODES_OUT)}
    edges = _read_csv(bge.EDGES_OUT)
    assert edges
    for row in edges:
        assert validate_row(row, schema) == [], row
        # node-existence integrity + evidence on every edge
        assert row["from_node_id"] in nodes
        assert row["to_node_id"] in nodes
        assert row["evidence_tier"] in ("T1", "T2", "T3", "T4")
        assert 0.0 <= float(row["confidence"]) <= 1.0


@pytest.mark.integration
def test_neo4j_exports_have_typed_headers():
    with (REPO_ROOT / bge.NEO4J_NODES_OUT).open(newline="", encoding="utf-8") as fh:
        node_header = next(csv.reader(fh))
    with (REPO_ROOT / bge.NEO4J_EDGES_OUT).open(newline="", encoding="utf-8") as fh:
        edge_header = next(csv.reader(fh))
    assert node_header[0] == "node_id:ID" and ":LABEL" in node_header
    assert edge_header[:3] == [":START_ID", ":END_ID", ":TYPE"]


# --------------------------------------------------------------------------- #
# gis_export
# --------------------------------------------------------------------------- #


@pytest.mark.integration
def test_gis_layer_manifest_on_disk_validates():
    manifest = json.loads((REPO_ROOT / bgm.OUT).read_text(encoding="utf-8"))
    assert "layers" in manifest and manifest["layers"]
    item_schema = _schema(bgm.SCHEMA)["properties"]["layers"]["items"]
    geometry_enum = set(item_schema["properties"]["geometry_type"]["enum"])
    type_enum = set(item_schema["properties"]["layer_type"]["enum"])
    status_enum = set(item_schema["properties"]["status"]["enum"])
    for layer in manifest["layers"]:
        assert validate_row(layer, item_schema) == [], layer
        assert layer["geometry_type"] in geometry_enum
        assert layer["layer_type"] in type_enum
        assert layer["status"] in status_enum


@pytest.mark.integration
def test_gis_geojson_layers_are_well_formed_when_present():
    """Any committed .geojson layer referenced by the manifest must parse as a
    FeatureCollection. Blocked layers have no file yet — that is allowed."""
    manifest = json.loads((REPO_ROOT / bgm.OUT).read_text(encoding="utf-8"))
    for layer in manifest["layers"]:
        path = REPO_ROOT / layer["path"]
        if path.suffix == ".geojson" and path.exists():
            gj = json.loads(path.read_text(encoding="utf-8"))
            assert gj.get("type") == "FeatureCollection", layer["path"]
            assert isinstance(gj.get("features"), list), layer["path"]
