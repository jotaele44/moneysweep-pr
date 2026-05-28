#!/usr/bin/env python3
"""Export PREPA continuity outputs to Neo4j- and GIS-ready files.

Inputs:
- prepa_titleiii_overlap_graph.json
- prepa_temporal_edges.csv
- prepa_continuity_clusters.csv

Outputs:
- neo4j_nodes.csv
- neo4j_edges.csv
- gis_entities.csv
- gis_edges.csv
- graph_export_manifest.json

GIS outputs are coordinate-ready. They include latitude/longitude columns but do
not geocode addresses by default. This avoids silent false precision.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def build_neo4j_nodes(graph: dict[str, Any], clusters: list[dict[str, str]]) -> list[dict[str, Any]]:
    cluster_by_id = {row.get("entity_id"): row for row in clusters}
    rows: list[dict[str, Any]] = []
    for node in graph.get("nodes", []):
        entity_id = node.get("entity_id", "")
        cluster = cluster_by_id.get(entity_id, {})
        rows.append(
            {
                "id:ID": entity_id,
                ":LABEL": "PREPAStakeholder",
                "raw_name": node.get("raw_name", ""),
                "normalized_name": node.get("normalized_name", ""),
                "sector": node.get("sector", ""),
                "source_document": node.get("source_document", ""),
                "evidence_tier": node.get("evidence_tier", ""),
                "continuity_score:float": cluster.get("continuity_score", "0"),
                "temporal_edges:int": cluster.get("temporal_edges", "0"),
            }
        )
    return rows


def build_neo4j_edges(graph: dict[str, Any], temporal_edges: list[dict[str, str]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for flag in graph.get("correlation_flags", []):
        record_id = flag.get("matched_record_id") or f"record:{flag.get('matched_dataset')}:{flag.get('entity_id')}"
        rows.append(
            {
                ":START_ID": flag.get("entity_id", ""),
                ":END_ID": record_id,
                ":TYPE": flag.get("flag_type", "PREPA_STAKEHOLDER_OVERLAP"),
                "matched_dataset": flag.get("matched_dataset", ""),
                "confidence:float": flag.get("confidence", 0),
                "evidence_tiers": ";".join(flag.get("evidence_tiers", [])),
            }
        )
    for edge in temporal_edges:
        milestone_id = "milestone:" + edge.get("milestone_date", "") + ":" + edge.get("milestone_name", "").replace(" ", "_")
        rows.append(
            {
                ":START_ID": edge.get("entity_id", ""),
                ":END_ID": milestone_id,
                ":TYPE": "TEMPORALLY_NEAR",
                "matched_dataset": edge.get("matched_dataset", ""),
                "confidence:float": edge.get("confidence", 0),
                "evidence_tiers": "T1_technical_primary",
            }
        )
    return rows


def build_gis_entities(graph: dict[str, Any], clusters: list[dict[str, str]]) -> list[dict[str, Any]]:
    cluster_by_id = {row.get("entity_id"): row for row in clusters}
    rows: list[dict[str, Any]] = []
    for node in graph.get("nodes", []):
        meta = node.get("service_metadata", {}) or {}
        entity_id = node.get("entity_id", "")
        cluster = cluster_by_id.get(entity_id, {})
        rows.append(
            {
                "entity_id": entity_id,
                "normalized_name": node.get("normalized_name", ""),
                "sector": node.get("sector", ""),
                "address_or_service_metadata": meta.get("address_or_service_metadata", ""),
                "emails": meta.get("emails", ""),
                "latitude": "",
                "longitude": "",
                "geocode_status": "not_geocoded",
                "continuity_score": cluster.get("continuity_score", "0"),
            }
        )
    return rows


def build_gis_edges(temporal_edges: list[dict[str, str]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for edge in temporal_edges:
        rows.append(
            {
                "entity_id": edge.get("entity_id", ""),
                "normalized_name": edge.get("normalized_name", ""),
                "sector": edge.get("sector", ""),
                "record_date": edge.get("record_date", ""),
                "milestone_date": edge.get("milestone_date", ""),
                "milestone_type": edge.get("milestone_type", ""),
                "milestone_name": edge.get("milestone_name", ""),
                "days_delta": edge.get("days_delta", ""),
                "confidence": edge.get("confidence", ""),
                "latitude": "",
                "longitude": "",
                "geocode_status": "not_geocoded",
            }
        )
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Export PREPA graph files for Neo4j and GIS")
    parser.add_argument("--graph-json", required=True, type=Path)
    parser.add_argument("--temporal-edges", required=True, type=Path)
    parser.add_argument("--clusters", required=True, type=Path)
    parser.add_argument("--outdir", required=True, type=Path)
    args = parser.parse_args()

    graph = load_json(args.graph_json)
    temporal_edges = load_csv(args.temporal_edges)
    clusters = load_csv(args.clusters)
    args.outdir.mkdir(parents=True, exist_ok=True)

    neo4j_nodes = build_neo4j_nodes(graph, clusters)
    neo4j_edges = build_neo4j_edges(graph, temporal_edges)
    gis_entities = build_gis_entities(graph, clusters)
    gis_edges = build_gis_edges(temporal_edges)

    files = {
        "neo4j_nodes": args.outdir / "neo4j_nodes.csv",
        "neo4j_edges": args.outdir / "neo4j_edges.csv",
        "gis_entities": args.outdir / "gis_entities.csv",
        "gis_edges": args.outdir / "gis_edges.csv",
        "manifest": args.outdir / "graph_export_manifest.json",
    }

    write_csv(files["neo4j_nodes"], neo4j_nodes, ["id:ID", ":LABEL", "raw_name", "normalized_name", "sector", "source_document", "evidence_tier", "continuity_score:float", "temporal_edges:int"])
    write_csv(files["neo4j_edges"], neo4j_edges, [":START_ID", ":END_ID", ":TYPE", "matched_dataset", "confidence:float", "evidence_tiers"])
    write_csv(files["gis_entities"], gis_entities, ["entity_id", "normalized_name", "sector", "address_or_service_metadata", "emails", "latitude", "longitude", "geocode_status", "continuity_score"])
    write_csv(files["gis_edges"], gis_edges, ["entity_id", "normalized_name", "sector", "record_date", "milestone_date", "milestone_type", "milestone_name", "days_delta", "confidence", "latitude", "longitude", "geocode_status"])

    manifest = {
        "neo4j_nodes": str(files["neo4j_nodes"]),
        "neo4j_edges": str(files["neo4j_edges"]),
        "gis_entities": str(files["gis_entities"]),
        "gis_edges": str(files["gis_edges"]),
        "warning": "Graph exports preserve correlation signals only. They do not encode allegations or causal findings.",
    }
    files["manifest"].write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
