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

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    import networkx as nx
except ImportError:
    print("ERROR: networkx not installed. Run: pip install networkx")
    sys.exit(1)

import pandas as pd

from scripts.config import MASTER_PATH, PROCESSED_DIR, PROJECT_ROOT, setup_logging

MIN_OBLIGATION_DEFAULT = 0
TOP_NODES_DEFAULT = 30


def load_master(root: Path) -> pd.DataFrame:
    enriched = root / "data" / "staging" / "processed" / "enrichment" / "master_enriched.csv"
    plain = root / "data" / "staging" / "processed" / "pr_contracts_master.csv"
    path = enriched if enriched.exists() else plain
    if not path.exists():
        raise FileNotFoundError(f"No master CSV at {path}")
    df = pd.read_csv(path, dtype=str, low_memory=False)
    df["obligated_amount"] = pd.to_numeric(df.get("obligated_amount"), errors="coerce").fillna(0)
    df["fiscal_year"] = pd.to_numeric(df.get("fiscal_year"), errors="coerce")
    df["vendor_name"] = df.get("vendor_name", pd.Series(dtype=str)).fillna("").str.strip()
    df["agency_name"] = df.get("agency_name", pd.Series(dtype=str)).fillna("UNKNOWN").str.strip()
    return df


def load_hierarchy(root: Path) -> pd.DataFrame | None:
    path = root / "data" / "staging" / "processed" / "enrichment" / "entity_hierarchy.csv"
    if not path.exists():
        return None
    return pd.read_csv(path, dtype=str, low_memory=False)


def build_graph(df: pd.DataFrame, hierarchy: pd.DataFrame | None, min_obligation: float) -> nx.DiGraph:
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
            vendor, agency,
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


def run(root: Path = None, min_obligation: float = MIN_OBLIGATION_DEFAULT, top_nodes: int = TOP_NODES_DEFAULT) -> dict:
    if root is None:
        root = PROJECT_ROOT

    graph_dir = root / "data" / "staging" / "processed" / "graph"
    graph_dir.mkdir(parents=True, exist_ok=True)

    logger = setup_logging("network_graph")
    logger.info("Building vendor-agency network graph...")

    df = load_master(root)
    hierarchy = load_hierarchy(root)

    if min_obligation > 0:
        df = df[df["obligated_amount"] >= min_obligation]
        logger.info(f"  Filtered to obligations ≥ ${min_obligation:,.0f}: {len(df):,} rows")

    G = build_graph(df, hierarchy, min_obligation)
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

    summary = {
        "total_nodes": G.number_of_nodes(),
        "total_edges": G.number_of_edges(),
        "vendor_nodes": len(vendor_nodes),
        "agency_nodes": len(agency_nodes),
        "parent_entity_nodes": len(parent_nodes),
        "top_node_by_pagerank": top1.get("node", ""),
        "top_node_type": top1.get("node_type", ""),
        "outputs": {
            "graphml": str(graphml_path),
            "top_nodes": str(graph_dir / "top_nodes.csv"),
            "summary": str(graph_dir / "network_summary.json"),
        }
    }
    summary_path = graph_dir / "network_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    logger.info(f"\nGraph summary:")
    logger.info(f"  Vendor nodes:  {len(vendor_nodes)}")
    logger.info(f"  Agency nodes:  {len(agency_nodes)}")
    logger.info(f"  Parent nodes:  {len(parent_nodes)}")
    logger.info(f"  Top PageRank:  {top1.get('node', '—')} ({top1.get('node_type', '')})")
    logger.info(f"  Summary:       {summary_path}")

    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Build vendor-agency network graph")
    parser.add_argument("--min-obligation", type=float, default=MIN_OBLIGATION_DEFAULT,
                        help="Minimum obligation to include an edge")
    parser.add_argument("--top-nodes", type=int, default=TOP_NODES_DEFAULT,
                        help="Number of top nodes to export")
    args = parser.parse_args()
    run(min_obligation=args.min_obligation, top_nodes=args.top_nodes)
    return 0


if __name__ == "__main__":
    sys.exit(main())
