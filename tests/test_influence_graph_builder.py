"""Tests for scripts/influence_graph_builder.py."""
import csv
import json
from pathlib import Path

import pytest

from scripts.influence_graph_builder import build_graph, _add_edge, _compute_metrics


@pytest.fixture
def graph_repo(tmp_path):
    proc = tmp_path / "data" / "staging" / "processed"
    proc.mkdir(parents=True)

    awards = [
        {"award_id": "AW001", "recipient_name": "Prime Corp", "recipient_uei": "PUEI001",
         "parent_uei": "PAR001", "obligated_amount": "5000000",
         "awarding_agency": "FEMA", "pop_county": "San Juan"},
        {"award_id": "AW002", "recipient_name": "Beta LLC", "recipient_uei": "PUEI002",
         "parent_uei": "", "obligated_amount": "2000000",
         "awarding_agency": "HUD", "pop_county": "Ponce"},
    ]
    _write_csv(proc / "pr_all_awards_master.csv", awards)

    exec_dir = proc / "execution"
    exec_dir.mkdir(parents=True)
    chains = [
        {"chain_id": "C001", "prime_name": "Prime Corp", "sub_name": "Sub LLC",
         "award_id": "AW001", "subaward_amount": "250000",
         "link_confidence": "0.8", "municipality": "San Juan", "asset_id": ""},
    ]
    _write_csv(exec_dir / "execution_chain_master.csv", chains)

    return tmp_path


def _write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


@pytest.mark.unit
def test_build_graph_returns_summary_keys(graph_repo):
    result = build_graph(graph_repo)
    for key in ("node_count", "edge_count", "graphml_written", "gexf_written",
                "top_25_written", "outputs"):
        assert key in result


@pytest.mark.unit
def test_build_graph_emits_output_files(graph_repo):
    build_graph(graph_repo)
    out = graph_repo / "data" / "staging" / "processed" / "graphs"
    assert (out / "entity_nodes.csv").exists()
    assert (out / "entity_edges.csv").exists()
    assert (out / "graph_metrics.csv").exists()
    assert (out / "top_25_control_entities.csv").exists()


@pytest.mark.unit
def test_build_graph_node_count(graph_repo):
    result = build_graph(graph_repo)
    # Nodes: FEMA, HUD (agencies), Prime Corp, Beta LLC (primes),
    # PAR001 (parent), Sub LLC (sub), San Juan, Ponce (municipalities)
    assert result["node_count"] >= 6


@pytest.mark.unit
def test_build_graph_edge_types(graph_repo):
    build_graph(graph_repo)
    out = graph_repo / "data" / "staging" / "processed" / "graphs"
    with (out / "entity_edges.csv").open(encoding="utf-8") as f:
        edges = list(csv.DictReader(f))
    types = {e["edge_type"] for e in edges}
    assert "awards_to" in types
    assert "subawards_to" in types


@pytest.mark.unit
def test_build_graph_parent_edge_emitted(graph_repo):
    build_graph(graph_repo)
    out = graph_repo / "data" / "staging" / "processed" / "graphs"
    with (out / "entity_edges.csv").open(encoding="utf-8") as f:
        edges = list(csv.DictReader(f))
    parent_edges = [e for e in edges if e["edge_type"] == "parent_of"]
    # AW001 has parent_uei=PAR001 → should produce a parent_of edge
    assert len(parent_edges) >= 1


@pytest.mark.unit
def test_build_graph_top25_has_25_or_fewer(graph_repo):
    build_graph(graph_repo)
    out = graph_repo / "data" / "staging" / "processed" / "graphs"
    with (out / "top_25_control_entities.csv").open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert 1 <= len(rows) <= 25


@pytest.mark.unit
def test_build_graph_summary_json_written(graph_repo):
    build_graph(graph_repo)
    summary_path = graph_repo / "data" / "staging" / "processed" / "graphs" / "influence_graph_summary.json"
    assert summary_path.exists()
    payload = json.loads(summary_path.read_text())
    assert "node_count" in payload
    assert "edge_count" in payload


@pytest.mark.unit
def test_add_edge_skips_empty_nodes():
    edges: list = []
    nodes: dict = {}
    _add_edge(edges, nodes, "", "target", "awards_to")
    _add_edge(edges, nodes, "source", "", "awards_to")
    assert len(edges) == 0
    assert len(nodes) == 0


@pytest.mark.unit
def test_add_edge_creates_node_entries():
    edges: list = []
    nodes: dict = {}
    _add_edge(edges, nodes, "Agency A", "Prime B", "awards_to", 1000, "test.csv", "E1",
              0.9, "agency", "prime")
    assert "Agency A" in nodes
    assert "Prime B" in nodes
    assert nodes["Agency A"]["node_type"] == "agency"
    assert nodes["Prime B"]["node_type"] == "prime"
    assert len(edges) == 1
    assert edges[0]["edge_type"] == "awards_to"


@pytest.mark.unit
def test_compute_metrics_contract_value_weight():
    nodes = {"A": {"node_type": "agency"}, "B": {"node_type": "prime"}}
    edges = [
        {"source": "A", "target": "B", "edge_type": "awards_to",
         "weight": 5000000.0, "manual_review_required": False},
    ]
    metrics = _compute_metrics(nodes, edges)
    by_node = {m["node"]: m for m in metrics}
    assert by_node["A"]["contract_value_weight"] == 5000000.0
    assert by_node["B"]["contract_value_weight"] == 5000000.0
