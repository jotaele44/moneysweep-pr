#!/usr/bin/env python3
"""Generate PREPA continuity clusters from overlap and temporal outputs.

This script consumes:
- prepa_titleiii_overlap_graph.json
- prepa_temporal_edges.csv

It prioritizes energy/fuel, legal, and infrastructure recurrence clusters across
PROMESA, Maria reconstruction, LUMA transition, and Genera takeover milestones.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

TARGET_SECTORS = {"energy_fuel", "legal", "infrastructure_contractor"}


def load_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def cluster_edges(edges: list[dict[str, str]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for edge in edges:
        sector = edge.get("sector", "unknown")
        if sector not in TARGET_SECTORS:
            continue
        key = edge.get("entity_id") or edge.get("normalized_name") or "unknown"
        grouped[key].append(edge)

    clusters: list[dict[str, Any]] = []
    for key, items in grouped.items():
        milestone_types = Counter(item.get("milestone_type", "unknown") for item in items)
        datasets = Counter(item.get("matched_dataset", "unknown") for item in items)
        names = Counter(item.get("normalized_name", "unknown") for item in items)
        sector = items[0].get("sector", "unknown")
        confidence_values = []
        for item in items:
            try:
                confidence_values.append(float(item.get("confidence", 0)))
            except ValueError:
                pass
        avg_confidence = sum(confidence_values) / len(confidence_values) if confidence_values else 0
        continuity_score = len(items) + (len(milestone_types) * 2) + (len(datasets) * 1.5) + avg_confidence
        clusters.append(
            {
                "entity_id": key,
                "normalized_name": names.most_common(1)[0][0],
                "sector": sector,
                "temporal_edges": len(items),
                "milestone_type_count": len(milestone_types),
                "dataset_count": len(datasets),
                "avg_confidence": round(avg_confidence, 3),
                "continuity_score": round(continuity_score, 3),
                "milestone_types": dict(milestone_types),
                "datasets": dict(datasets),
            }
        )
    return sorted(clusters, key=lambda item: item["continuity_score"], reverse=True)


def write_clusters_csv(clusters: list[dict[str, Any]], output_csv: Path) -> None:
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "entity_id",
        "normalized_name",
        "sector",
        "temporal_edges",
        "milestone_type_count",
        "dataset_count",
        "avg_confidence",
        "continuity_score",
        "milestone_types",
        "datasets",
    ]
    with output_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for cluster in clusters:
            row = dict(cluster)
            row["milestone_types"] = json.dumps(row["milestone_types"], sort_keys=True)
            row["datasets"] = json.dumps(row["datasets"], sort_keys=True)
            writer.writerow(row)


def write_markdown(clusters: list[dict[str, Any]], output_md: Path) -> None:
    lines = [
        "# PREPA Contract Continuity Cluster Report",
        "",
        "## Scope",
        "",
        "This report ranks PREPA Title III stakeholder overlap clusters by temporal recurrence across restructuring, reconstruction, privatization, and generation-transition milestones.",
        "",
        "## Constraint",
        "",
        "Continuity score is a triage metric. It is not evidence of misconduct, fraud, or coordination.",
        "",
        "## Top Clusters",
        "",
        "| Rank | Entity | Sector | Temporal Edges | Milestone Types | Datasets | Avg Confidence | Continuity Score |",
        "|---:|---|---|---:|---:|---:|---:|---:|",
    ]
    for idx, cluster in enumerate(clusters[:50], start=1):
        lines.append(
            f"| {idx} | {cluster['normalized_name']} | {cluster['sector']} | {cluster['temporal_edges']} | {cluster['milestone_type_count']} | {cluster['dataset_count']} | {cluster['avg_confidence']:.3f} | {cluster['continuity_score']:.3f} |"
        )
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_md.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build PREPA continuity cluster report")
    parser.add_argument("--graph-json", required=True, type=Path)
    parser.add_argument("--temporal-edges", required=True, type=Path)
    parser.add_argument("--outdir", required=True, type=Path)
    args = parser.parse_args()

    _ = load_json(args.graph_json)
    edges = load_csv(args.temporal_edges)
    clusters = cluster_edges(edges)

    args.outdir.mkdir(parents=True, exist_ok=True)
    output_csv = args.outdir / "prepa_continuity_clusters.csv"
    output_md = args.outdir / "prepa_continuity_cluster_report.md"
    output_json = args.outdir / "prepa_continuity_clusters.json"

    write_clusters_csv(clusters, output_csv)
    write_markdown(clusters, output_md)
    output_json.write_text(json.dumps({"clusters": clusters}, indent=2), encoding="utf-8")

    print(json.dumps({"clusters": len(clusters), "csv": str(output_csv), "report": str(output_md), "json": str(output_json)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
