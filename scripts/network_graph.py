"""
Network Graph — Vendor-Agency Contract Network

Builds a weighted directed graph of vendor→agency contract relationships,
with parent-child hierarchy edges. Exports to GraphML (Gephi) and JSON.

Nodes:  vendors (or parent entities), agencies
Edges:  vendor→agency (weight = total obligation),
        parent→child (hierarchy, from entity_hierarchy.csv)

Centrality metrics computed: degree, betweenness, PageRank.

Usage:
  python3 scripts/network_graph.py
  python3 scripts/network_graph.py --min-obligation 100000   # filter small contracts
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    import networkx as nx
except ImportError as exc:  # pragma: no cover
    # Raise rather than sys.exit() -- see the note in
    # scripts/regenerate_registry_json.py.
    raise ImportError("networkx not installed. Run: pip install networkx") from exc

import pandas as pd

from scripts.config import PROJECT_ROOT, setup_logging
from moneysweep.validation.production_status import load_current_status

MIN_OBLIGATION_DEFAULT = 0
TOP_NODES_DEFAULT = 30


def load_master(root: Path) -> pd.DataFrame:
    enriched = root / "data" / "staging" / "processed" / "enrichment" / "master_enriched.csv"
    plain = root / "data" / "staging" / "processed" / "pr_contracts_master.csv"
    unified = root / "data" / "staging" / "processed" / "pr_all_awards_master.csv"
    path = enriched if enriched.exists() else (plain if plain.exists() else unified)
    if not path.exists():
        raise FileNotFoundError(f"No master CSV at {path}")
    df = pd.read_csv(path, dtype=str, low_memory=False)
    df["obligated_amount"] = pd.to_numeric(df.get("obligated_amount"), errors="coerce").fillna(0)
    df["fiscal_year"] = pd.to_numeric(df.get("fiscal_year"), errors="coerce")
    if "vendor_name" not in df.columns:
        df["vendor_name"] = df.get("recipient_name", pd.Series(dtype=str)).fillna("").str.strip()
    else:
        df["vendor_name"] = df["vendor_name"].fillna("").str.strip()
    if "agency_name" not in df.columns:
        df["agency_name"] = (
            df.get("awarding_agency", pd.Series(dtype=str)).fillna("UNKNOWN").str.strip()
        )
    else:
        df["agency_name"] = df["agency_name"].fillna("UNKNOWN").str.strip()
    return df


def load_hierarchy(root: Path) -> pd.DataFrame | None:
    path = root / "data" / "staging" / "processed" / "enrichment" / "entity_hierarchy.csv"
    if not path.exists():
        return None
    return pd.read_csv(path, dtype=str, low_memory=False, keep_default_na=False)


# Curated parent/control relationships that carry a control semantic — the
# federation cares about these hierarchy edges regardless of award activity.
PARENT_MAP_CONTROL_TYPES = (
    "INSTRUMENTALITY_OF",
    "P3_OPERATOR_OF",
    "CONCESSION_OPERATOR_OF",
)


def load_parent_map(root: Path) -> pd.DataFrame | None:
    """Load the curated entity parent/control map (data/reference/entity_parent_map.csv).

    Columns: relation_id, parent_entity_id, child_entity_id, relationship_type,
    source_id, evidence_tier, confidence, notes.
    """
    path = root / "data" / "reference" / "entity_parent_map.csv"
    if not path.exists():
        return None
    return pd.read_csv(path, dtype=str, low_memory=False, keep_default_na=False)


def add_parent_map_edges(G: nx.DiGraph, parent_map: pd.DataFrame | None) -> int:
    """Add parent_entity nodes and hierarchy/control edges from the parent map.

    Returns the number of control edges added. Parent nodes are typed
    ``parent_entity``; child nodes are added as ``controlled_entity`` only when
    not already present (never clobbering an existing vendor/agency/parent node).
    Only the control relationship types in PARENT_MAP_CONTROL_TYPES are wired.
    """
    if parent_map is None or parent_map.empty:
        return 0

    edges_added = 0
    for _, row in parent_map.iterrows():
        rel_type = (row.get("relationship_type") or "").strip()
        if rel_type not in PARENT_MAP_CONTROL_TYPES:
            continue
        parent = (row.get("parent_entity_id") or "").strip()
        child = (row.get("child_entity_id") or "").strip()
        if not parent or not child or parent == child:
            continue

        # Parent always carries the parent_entity type (a parent may appear as a
        # child elsewhere, e.g. PREPA/HTA — set node_type on the parent add and
        # only default it on the child add so neither role clobbers the other).
        if G.has_node(parent):
            G.nodes[parent]["node_type"] = "parent_entity"
            G.nodes[parent].setdefault("label", parent[:60])
        else:
            G.add_node(parent, node_type="parent_entity", label=parent[:60])
        if not G.has_node(child):
            G.add_node(child, node_type="controlled_entity", label=child[:60])

        try:
            confidence = float(row.get("confidence") or 0.0)
        except ValueError:
            confidence = 0.0
        G.add_edge(
            parent,
            child,
            edge_type="control",
            relationship_type=rel_type,
            weight=1.0,
            evidence_tier=(row.get("evidence_tier") or "").strip(),
            confidence=round(confidence, 4),
            relation_id=(row.get("relation_id") or "").strip(),
        )
        edges_added += 1
    return edges_added


def build_graph(
    df: pd.DataFrame, hierarchy: pd.DataFrame | None, min_obligation: float
) -> nx.DiGraph:
    G = nx.DiGraph()

    # Vendor → Agency edges
    edges = (
        df.groupby(["vendor_name", "agency_name"])
        .agg(
            weight=("obligated_amount", "sum"),
            contract_count=("obligated_amount", "count"),
            fy_min=("fiscal_year", "min"),
            fy_max=("fiscal_year", "max"),
        )
        .reset_index()
    )
    edges = edges[edges["weight"] >= min_obligation]

    for _, row in edges.iterrows():
        vendor = row["vendor_name"]
        agency = row["agency_name"]
        weight = row["weight"]

        if not G.has_node(vendor):
            G.add_node(vendor, node_type="vendor", label=vendor[:60])
        if not G.has_node(agency):
            G.add_node(agency, node_type="agency", label=agency[:60])

        G.add_edge(
            vendor,
            agency,
            weight=round(weight, 2),
            contract_count=int(row["contract_count"]),
            fy_min=int(row["fy_min"]) if pd.notna(row["fy_min"]) else 0,
            fy_max=int(row["fy_max"]) if pd.notna(row["fy_max"]) else 0,
            edge_type="award",
        )

    # Parent → Child hierarchy edges
    if hierarchy is not None:
        for _, row in hierarchy.iterrows():
            child = (row.get("vendor_name") or "").strip()
            parent = (row.get("parent_name") or "").strip()
            if not child or not parent or child == parent:
                continue
            if not G.has_node(parent):
                G.add_node(parent, node_type="parent_entity", label=parent[:60])
            G.add_edge(parent, child, edge_type="hierarchy", weight=1.0)

    return G


def compute_metrics(G: nx.DiGraph) -> dict[str, dict]:
    metrics = {}
    award_subgraph = nx.DiGraph(
        (u, v, d) for u, v, d in G.edges(data=True) if d.get("edge_type") == "award"
    )
    if award_subgraph.number_of_nodes() == 0:
        return {}

    degree = dict(G.degree())
    in_deg = dict(G.in_degree())
    out_deg = dict(G.out_degree())

    try:
        pagerank = nx.pagerank(award_subgraph, weight="weight", max_iter=200)
    except Exception:
        pagerank = {n: 0.0 for n in G.nodes()}

    # Betweenness on undirected projection (too slow on full digraph for large graphs)
    undirected = G.to_undirected()
    try:
        betweenness = nx.betweenness_centrality(undirected, normalized=True, weight="weight")
    except Exception:
        betweenness = {n: 0.0 for n in G.nodes()}

    for node in G.nodes():
        metrics[node] = {
            "node": node,
            "node_type": G.nodes[node].get("node_type", "unknown"),
            "degree": degree.get(node, 0),
            "in_degree": in_deg.get(node, 0),
            "out_degree": out_deg.get(node, 0),
            "pagerank": round(pagerank.get(node, 0), 6),
            "betweenness": round(betweenness.get(node, 0), 6),
        }

    return metrics


def run(
    root: Path | None = None,
    min_obligation: float = MIN_OBLIGATION_DEFAULT,
    top_nodes: int = TOP_NODES_DEFAULT,
) -> dict:
    if root is None:
        root = PROJECT_ROOT

    graph_dir = root / "data" / "staging" / "processed" / "graph"
    graph_dir.mkdir(parents=True, exist_ok=True)

    logger = setup_logging("network_graph")
    logger.info("Building vendor-agency network graph...")

    df = load_master(root)
    hierarchy = load_hierarchy(root)
    parent_map = load_parent_map(root)

    if min_obligation > 0:
        df = df[df["obligated_amount"] >= min_obligation]
        logger.info(f"  Filtered to obligations ≥ ${min_obligation:,.0f}: {len(df):,} rows")

    G = build_graph(df, hierarchy, min_obligation)

    # Overlay curated parent/control hierarchy (entity_parent_map.csv) so the
    # federation's instrumentality / P3 / concession control edges are present
    # alongside the vendor→agency award graph.
    control_edges = add_parent_map_edges(G, parent_map)
    logger.info(f"  Parent-map control edges added: {control_edges}")

    logger.info(
        f"  Graph: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges "
        f"({G.number_of_nodes()} vendors/agencies)"
    )

    # Compute metrics
    metrics = compute_metrics(G)

    # Export GraphML
    graphml_path = graph_dir / "network.graphml"
    nx.write_graphml(G, str(graphml_path))
    logger.info(f"  GraphML written: {graphml_path.name}")

    # Flat CSV export of all edges for tabular analysis
    edge_rows = []
    for u, v, data in G.edges(data=True):
        edge_rows.append(
            {
                "source_entity": u,
                "target": v,
                "total_obligation": data.get("weight", 0),
                "contract_count": data.get("contract_count", 0),
                "fy_min": data.get("fy_min", ""),
                "fy_max": data.get("fy_max", ""),
                "edge_type": data.get("edge_type", ""),
            }
        )
    edges_path = graph_dir / "entity_edges.csv"
    pd.DataFrame(edge_rows).to_csv(edges_path, index=False, encoding="utf-8")
    logger.info(f"  Entity edges: {edges_path.name} ({len(edge_rows):,} edges)")

    # Top nodes by PageRank
    if metrics:
        top = sorted(metrics.values(), key=lambda x: x["pagerank"], reverse=True)[:top_nodes]
        import csv

        top_path = graph_dir / "top_nodes.csv"
        with open(top_path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(top[0].keys()))
            w.writeheader()
            w.writerows(top)
        logger.info(f"  Top {top_nodes} nodes by PageRank: {top_path.name}")

        top1 = top[0] if top else {}
    else:
        top1 = {}

    # Summary JSON
    vendor_nodes = [n for n, d in G.nodes(data=True) if d.get("node_type") == "vendor"]
    agency_nodes = [n for n, d in G.nodes(data=True) if d.get("node_type") == "agency"]
    parent_nodes = [n for n, d in G.nodes(data=True) if d.get("node_type") == "parent_entity"]
    status_payload = load_current_status(root)

    summary = {
        "total_nodes": G.number_of_nodes(),
        "total_edges": G.number_of_edges(),
        "vendor_nodes": len(vendor_nodes),
        "agency_nodes": len(agency_nodes),
        "parent_entity_nodes": len(parent_nodes),
        "control_edges": control_edges,
        "production_status": status_payload["production_status"],
        "production_status_message": status_payload["status_message"],
        "top_node_by_pagerank": top1.get("node", ""),
        "top_node_type": top1.get("node_type", ""),
        "outputs": {
            "graphml": str(graphml_path),
            "top_nodes": str(graph_dir / "top_nodes.csv"),
            "entity_edges": str(edges_path),
            "summary": str(graph_dir / "network_summary.json"),
        },
    }
    summary_path = graph_dir / "network_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    logger.info("\nGraph summary:")
    logger.info(f"  Vendor nodes:  {len(vendor_nodes)}")
    logger.info(f"  Agency nodes:  {len(agency_nodes)}")
    logger.info(f"  Parent nodes:  {len(parent_nodes)}")
    logger.info(f"  Top PageRank:  {top1.get('node', '—')} ({top1.get('node_type', '')})")
    logger.info(f"  Summary:       {summary_path}")

    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Build vendor-agency network graph")
    parser.add_argument(
        "--min-obligation",
        type=float,
        default=MIN_OBLIGATION_DEFAULT,
        help="Minimum obligation to include an edge",
    )
    parser.add_argument(
        "--top-nodes", type=int, default=TOP_NODES_DEFAULT, help="Number of top nodes to export"
    )
    args = parser.parse_args()
    run(min_obligation=args.min_obligation, top_nodes=args.top_nodes)
    return 0


if __name__ == "__main__":
    sys.exit(main())
