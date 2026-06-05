"""Output snapshot guard (Gate ``testing``, item ``output_snapshot_tests``).

For every top-form reference producer, regenerate its rows in memory and assert
the bytes are identical to the committed output. This is the single meta-guard
that catches any drift between a producer and its checked-in artifact, across
the entity-master, influence, debt_fiscal, gis, and graph_export gates.

Fully offline. Each producer is regenerated into a temp path (never the real
output) so the working tree is never touched.
"""
from __future__ import annotations

import importlib
import json

import pytest

from scripts import build_graph_export as bge
from scripts import build_gis_layer_manifest as bgm
from scripts import build_municipality_crosswalk as bmc

REPO_ROOT = bmc.REPO_ROOT

# (module path, attribute naming the committed CSV output). Every one of these
# exposes the uniform build_rows(root) + _write(rows, path) producer contract.
STANDARD_PRODUCERS = [
    ("scripts.build_entity_master", "ENTITY_MASTER_OUT"),
    ("scripts.build_entity_aliases", "ENTITY_ALIASES_OUT"),
    ("scripts.build_entity_parent_map", "PARENT_MAP_OUT"),
    ("scripts.build_person_master", "PERSON_MASTER_OUT"),
    ("scripts.build_agency_master", "AGENCY_MASTER_OUT"),
    ("scripts.build_entity_resolution_review_queue", "REVIEW_QUEUE_OUT"),
    ("scripts.build_influence_edges", "OUT"),
    ("scripts.build_debt_instruments", "OUT"),
    ("scripts.build_creditor_mapping", "OUT"),
    ("scripts.build_fiscal_control_events", "OUT"),
    ("scripts.build_foia_tracker", "OUT"),
    ("scripts.build_foia_yield_tracking", "OUT"),
    ("scripts.build_geo_reason_codes", "OUT"),
    ("scripts.build_hq_bias_reference", "OUT"),
]


@pytest.mark.integration
@pytest.mark.parametrize("module_path,out_attr", STANDARD_PRODUCERS)
def test_producer_regenerates_identically(module_path, out_attr, tmp_path):
    mod = importlib.import_module(module_path)
    committed = (REPO_ROOT / getattr(mod, out_attr)).read_bytes()
    rows = mod.build_rows(REPO_ROOT)
    regenerated = tmp_path / "out.csv"
    mod._write(rows, regenerated)
    assert regenerated.read_bytes() == committed, f"{module_path} drifted from {getattr(mod, out_attr)}"


@pytest.mark.integration
def test_graph_export_regenerates_identically(tmp_path):
    nodes = bge.build_nodes(REPO_ROOT)
    edges = bge.build_edges(REPO_ROOT, {n["node_id"] for n in nodes})
    nodes_tmp = tmp_path / "nodes.csv"
    edges_tmp = tmp_path / "edges.csv"
    bge._write_csv(nodes, bge.NODE_COLUMNS, nodes_tmp)
    bge._write_csv(edges, bge.EDGE_COLUMNS, edges_tmp)
    assert nodes_tmp.read_bytes() == (REPO_ROOT / bge.NODES_OUT).read_bytes()
    assert edges_tmp.read_bytes() == (REPO_ROOT / bge.EDGES_OUT).read_bytes()


@pytest.mark.integration
def test_gis_layer_manifest_regenerates_identically():
    built = bgm.build_manifest(REPO_ROOT)
    committed = json.loads((REPO_ROOT / bgm.OUT).read_text(encoding="utf-8"))
    assert built == committed


@pytest.mark.integration
def test_municipality_crosswalk_is_locked():
    # The crosswalk is the authority (no _write); the lock is that check() passes.
    rows = bmc.build_rows(REPO_ROOT)
    assert bmc.check(rows, REPO_ROOT) == []
    assert len(rows) == 78
