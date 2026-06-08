#!/usr/bin/env python3
"""Run the PREPA Title III stakeholder overlap pipeline end-to-end.

This runner expects that the PREPA PDF has already been converted to text or that
text has been supplied manually. It then:
1. Parses the PREPA service matrix into canonical CSV.
2. Loads normalized FPDS/USASpending/FSRS-style CSV datasets.
3. Generates a confidence-ranked overlap intelligence report.
4. Produces a sector heatmap CSV and Markdown summary.

The output is correlation intelligence only. It is not an allegation engine.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from prepa_service_matrix_parser import parse_text, write_csv
from contract_sweeper.modules.prepa_titleiii_entity_graph import (
    build_nodes,
    export_graph,
    match_contract_records,
)


def load_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_heatmap(nodes: list[Any], flags: list[Any], output_csv: Path) -> None:
    sector_counts = Counter(node.sector.value for node in nodes)
    flag_counts: dict[str, Counter[str]] = defaultdict(Counter)
    for flag in flags:
        sector = str(flag.metadata.get("sector", "unknown"))
        flag_counts[sector][flag.flag_type.value] += 1

    output_csv.parent.mkdir(parents=True, exist_ok=True)
    with output_csv.open("w", encoding="utf-8", newline="") as handle:
        fieldnames = ["sector", "stakeholder_nodes", "total_flags", "flag_breakdown"]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for sector in sorted(set(sector_counts) | set(flag_counts)):
            total_flags = sum(flag_counts[sector].values())
            writer.writerow(
                {
                    "sector": sector,
                    "stakeholder_nodes": sector_counts.get(sector, 0),
                    "total_flags": total_flags,
                    "flag_breakdown": json.dumps(dict(flag_counts[sector]), sort_keys=True),
                }
            )


def write_markdown_summary(
    nodes: list[Any], flags: list[Any], heatmap_csv: Path, output_md: Path
) -> None:
    top_flags = sorted(flags, key=lambda flag: flag.confidence, reverse=True)[:25]
    sector_counts = Counter(node.sector.value for node in nodes)

    lines = [
        "# PREPA Title III Stakeholder Overlap Report",
        "",
        "## Scope",
        "",
        "This report correlates PREPA PROMESA Title III service-matrix stakeholders against normalized contract/procurement datasets.",
        "It reports overlap signals only. It does not assert misconduct.",
        "",
        "## Summary",
        "",
        f"- Stakeholder nodes: {len(nodes)}",
        f"- Correlation flags: {len(flags)}",
        f"- Heatmap CSV: `{heatmap_csv}`",
        "",
        "## Sector Distribution",
        "",
        "| Sector | Nodes |",
        "|---|---:|",
    ]
    for sector, count in sector_counts.most_common():
        lines.append(f"| {sector} | {count} |")

    lines.extend(
        [
            "",
            "## Top Confidence Flags",
            "",
            "| Rank | Entity | Flag | Dataset | Confidence |",
            "|---:|---|---|---|---:|",
        ]
    )
    for idx, flag in enumerate(top_flags, start=1):
        lines.append(
            f"| {idx} | {flag.normalized_name} | {flag.flag_type.value} | {flag.matched_dataset} | {flag.confidence:.3f} |"
        )

    lines.extend(
        [
            "",
            "## Analytic Constraint",
            "",
            "A PREPA Title III service-matrix appearance means the party was noticed or otherwise listed in a procedural stakeholder matrix. Any investigative conclusion requires corroboration from contract records, procurement files, fiscal plans, litigation dockets, or agency disclosures.",
        ]
    )

    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_md.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run PREPA service-matrix overlap pipeline")
    parser.add_argument(
        "--prepa-text", required=True, type=Path, help="Text/OCR dump from PREPA service matrix PDF"
    )
    parser.add_argument(
        "--datasets", nargs="+", required=True, help="Normalized FPDS/USASpending/FSRS CSV files"
    )
    parser.add_argument("--outdir", default=Path("outputs/prepa_titleiii"), type=Path)
    args = parser.parse_args()

    args.outdir.mkdir(parents=True, exist_ok=True)
    canonical_csv = args.outdir / "prepa_titleiii_stakeholders.csv"
    graph_json = args.outdir / "prepa_titleiii_overlap_graph.json"
    heatmap_csv = args.outdir / "prepa_titleiii_sector_heatmap.csv"
    report_md = args.outdir / "prepa_titleiii_overlap_report.md"
    summary_json = args.outdir / "prepa_titleiii_pipeline_summary.json"

    text = args.prepa_text.read_text(encoding="utf-8", errors="replace")
    parsed_rows = parse_text(text)
    write_csv(parsed_rows, canonical_csv)

    nodes = build_nodes(parsed_rows, source_document="PREPA Title III service matrix")
    flags = []
    for dataset in args.datasets:
        dataset_path = Path(dataset)
        flags.extend(
            match_contract_records(
                nodes,
                load_csv(dataset_path),
                dataset_name=dataset_path.name,
            )
        )
    flags = sorted(flags, key=lambda flag: flag.confidence, reverse=True)

    export_graph(nodes, flags, graph_json)
    write_heatmap(nodes, flags, heatmap_csv)
    write_markdown_summary(nodes, flags, heatmap_csv, report_md)

    summary = {
        "canonical_csv": str(canonical_csv),
        "graph_json": str(graph_json),
        "heatmap_csv": str(heatmap_csv),
        "report_md": str(report_md),
        "stakeholder_nodes": len(nodes),
        "correlation_flags": len(flags),
        "datasets": [str(Path(dataset)) for dataset in args.datasets],
        "top_confidence": flags[0].confidence if flags else 0,
    }
    summary_json.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
