"""Tests for the top-form Graph Export producer (Gate ``graph_export``).

Fully offline: the producer projects the committed master registries into a
node/edge property-graph and validates against ``schemas/graph_nodes.schema.json``
and ``schemas/graph_edges.schema.json`` via the stdlib canonical_v1 schema
interpreter (no ``jsonschema`` dependency).
"""
from __future__ import annotations

import csv
import json
import re

import pytest

from contract_sweeper.validation.canonical_v1_schema import validate_row
from scripts import build_graph_export as bge

REPO_ROOT = bge.REPO_ROOT


@pytest.fixture(scope="module")
def nodes():
    return bge.build_nodes(REPO_ROOT)


@pytest.fixture(scope="module")
def edges(nodes):
    return bge.build_edges(REPO_ROOT, {n["node_id"] for n in nodes})


@pytest.fixture(scope="module")
def node_schema():
    return json.loads((REPO_ROOT / bge.NODE_SCHEMA).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def edge_schema():
    return json.loads((REPO_ROOT / bge.EDGE_SCHEMA).read_text(encoding="utf-8"))


@pytest.mark.unit
def test_check_passes(nodes, edges):
    assert bge.check(nodes, edges, REPO_ROOT) == []


@pytest.mark.unit
def test_node_counts(nodes):
    # 26 entities + 78 municipios + 60 people.
    assert len(nodes) == 164
    by_type: dict[str, int] = {}
    for n in nodes:
        by_type[n["node_type"]] = by_type.get(n["node_type"], 0) + 1
    assert by_type["municipality"] == 78
    assert by_type["person"] == 60
    assert by_type["government_agency"] + by_type["organization"] == 26


@pytest.mark.unit
def test_edge_count_and_types(edges):
    assert len(edges) == 30
    types = {e["edge_type"] for e in edges}
    assert "PARENT_OF" in types
    assert "REGISTERED_LOBBYING_FOR" in types
    assert "BOARD_MEMBER_OF" in types


@pytest.mark.unit
def test_every_node_validates(nodes, node_schema):
    for node in nodes:
        assert validate_row(node, node_schema) == [], node


@pytest.mark.unit
def test_every_edge_validates(edges, edge_schema):
    for edge in edges:
        assert validate_row(edge, edge_schema) == [], edge


@pytest.mark.unit
def test_ids_unique_and_match_pattern(nodes, edges, node_schema):
    node_ids = [n["node_id"] for n in nodes]
    assert len(set(node_ids)) == len(node_ids)
    pattern = node_schema["properties"]["node_id"]["pattern"]
    assert all(re.fullmatch(pattern, i) for i in node_ids)
    edge_ids = [e["edge_id"] for e in edges]
    assert len(set(edge_ids)) == len(edge_ids)


@pytest.mark.unit
def test_edge_endpoints_are_nodes(nodes, edges):
    """Node-existence integrity: every edge endpoint resolves to a node."""
    known = {n["node_id"] for n in nodes}
    for e in edges:
        assert e["from_node_id"] in known, e
        assert e["to_node_id"] in known, e


@pytest.mark.unit
def test_every_edge_has_evidence(edges):
    """The graph_export 'evidence_confidence' invariant."""
    for e in edges:
        assert e["evidence_tier"] in ("T1", "T2", "T3", "T4"), e
        assert isinstance(e["confidence"], float)
        assert 0.0 <= e["confidence"] <= 1.0


@pytest.mark.unit
def test_known_edges_present(nodes, edges):
    by_name = {n["canonical_name"]: n["node_id"] for n in nodes}
    commonwealth = by_name["Commonwealth of Puerto Rico"]
    prepa = by_name["Puerto Rico Electric Power Authority"]
    luma = by_name["LUMA Energy"]
    fomb = by_name["Financial Oversight and Management Board for Puerto Rico"]
    # Commonwealth PARENT_OF PREPA
    assert any(e["from_node_id"] == commonwealth and e["to_node_id"] == prepa
               and e["edge_type"] == "PARENT_OF" for e in edges)
    # LUMA operates PREPA assets -> RELATED_TO with the precise relationship in notes
    luma_edge = next(e for e in edges if e["to_node_id"] == luma)
    assert luma_edge["from_node_id"] == prepa
    assert luma_edge["edge_type"] == "RELATED_TO"
    assert "P3_OPERATOR_OF" in luma_edge["notes"]
    # FOMB has board members
    assert any(e["to_node_id"] == fomb and e["edge_type"] == "BOARD_MEMBER_OF"
               for e in edges)


@pytest.mark.integration
def test_csv_exports_regenerate_identically(nodes, edges):
    nodes_path = REPO_ROOT / bge.NODES_OUT
    edges_path = REPO_ROOT / bge.EDGES_OUT
    assert nodes_path.exists() and edges_path.exists(), \
        "exports not written — run scripts/build_graph_export.py"
    with nodes_path.open(newline="", encoding="utf-8") as fh:
        on_disk_nodes = list(csv.DictReader(fh))
    with edges_path.open(newline="", encoding="utf-8") as fh:
        on_disk_edges = list(csv.DictReader(fh))
    assert len(on_disk_nodes) == len(nodes)
    assert len(on_disk_edges) == len(edges)
    for built, on_disk in zip(nodes, on_disk_nodes):
        assert on_disk["node_id"] == built["node_id"]
        assert on_disk["node_type"] == built["node_type"]
    for built, on_disk in zip(edges, on_disk_edges):
        assert on_disk["edge_id"] == built["edge_id"]
        assert on_disk["edge_type"] == built["edge_type"]


@pytest.mark.integration
def test_neo4j_headers(nodes, edges):
    nodes_path = REPO_ROOT / bge.NEO4J_NODES_OUT
    edges_path = REPO_ROOT / bge.NEO4J_EDGES_OUT
    assert nodes_path.exists() and edges_path.exists(), \
        "neo4j exports not written — run scripts/build_graph_export.py"
    with nodes_path.open(newline="", encoding="utf-8") as fh:
        node_header = next(csv.reader(fh))
    with edges_path.open(newline="", encoding="utf-8") as fh:
        edge_header = next(csv.reader(fh))
    assert node_header[0] == "node_id:ID"
    assert ":LABEL" in node_header
    assert "confidence:float" in node_header
    assert edge_header[:3] == [":START_ID", ":END_ID", ":TYPE"]
    assert "confidence:float" in edge_header
