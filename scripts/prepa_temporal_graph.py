#!/usr/bin/env python3
"""Build a temporal graph from PREPA overlap output and milestone data.

Inputs:
- prepa_titleiii_overlap_graph.json from prepa_run_full_pipeline.py
- milestones CSV containing: date,event_type,event_name,description

Outputs:
- temporal edges CSV
- temporal graph JSON
- sector recurrence summary CSV

This module links stakeholder overlap flags to restructuring, reconstruction,
and privatization-era milestones using configurable date windows.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from datetime import datetime, date
from pathlib import Path
from typing import Any

DATE_FIELDS = (
    "action_date",
    "award_date",
    "period_of_performance_start_date",
    "date_signed",
    "modification_date",
    "start_date",
    "transaction_obligated_date",
)


def parse_date(value: Any) -> date | None:
    if value is None:
        return None
    text = str(value).strip()[:10]
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def load_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def choose_record_date(record: dict[str, Any]) -> date | None:
    for field in DATE_FIELDS:
        parsed = parse_date(record.get(field))
        if parsed:
            return parsed
    return None


def within_days(a: date, b: date, window_days: int) -> bool:
    return abs((a - b).days) <= window_days


def build_temporal_edges(
    graph: dict[str, Any], milestones: list[dict[str, str]], window_days: int
) -> list[dict[str, Any]]:
    parsed_milestones = []
    for milestone in milestones:
        milestone_date = parse_date(milestone.get("date"))
        if milestone_date:
            parsed_milestones.append((milestone_date, milestone))

    edges: list[dict[str, Any]] = []
    for flag in graph.get("correlation_flags", []):
        metadata = flag.get("metadata", {}) or {}
        record = metadata.get("matched_record", {}) or {}
        record_date = choose_record_date(record)
        if not record_date:
            continue
        for milestone_date, milestone in parsed_milestones:
            if within_days(record_date, milestone_date, window_days):
                edges.append(
                    {
                        "entity_id": flag.get("entity_id"),
                        "normalized_name": flag.get("normalized_name"),
                        "sector": metadata.get("sector", "unknown"),
                        "flag_type": flag.get("flag_type"),
                        "matched_dataset": flag.get("matched_dataset"),
                        "matched_record_id": flag.get("matched_record_id"),
                        "record_date": record_date.isoformat(),
                        "milestone_date": milestone_date.isoformat(),
                        "milestone_type": milestone.get("event_type", ""),
                        "milestone_name": milestone.get("event_name", ""),
                        "days_delta": (record_date - milestone_date).days,
                        "confidence": flag.get("confidence"),
                    }
                )
    return sorted(
        edges, key=lambda item: (item["sector"], item["record_date"], item["normalized_name"])
    )


def write_edges_csv(edges: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "entity_id",
        "normalized_name",
        "sector",
        "flag_type",
        "matched_dataset",
        "matched_record_id",
        "record_date",
        "milestone_date",
        "milestone_type",
        "milestone_name",
        "days_delta",
        "confidence",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(edges)


def write_sector_summary(edges: list[dict[str, Any]], path: Path) -> None:
    sector_counter = Counter(edge["sector"] for edge in edges)
    type_counter: dict[str, Counter[str]] = defaultdict(Counter)
    for edge in edges:
        type_counter[edge["sector"]][edge["milestone_type"]] += 1

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=["sector", "temporal_edges", "milestone_type_breakdown"]
        )
        writer.writeheader()
        for sector, count in sector_counter.most_common():
            writer.writerow(
                {
                    "sector": sector,
                    "temporal_edges": count,
                    "milestone_type_breakdown": json.dumps(
                        dict(type_counter[sector]), sort_keys=True
                    ),
                }
            )


def main() -> int:
    parser = argparse.ArgumentParser(description="Build PREPA temporal overlap graph")
    parser.add_argument("--graph-json", required=True, type=Path)
    parser.add_argument("--milestones", required=True, type=Path)
    parser.add_argument("--outdir", required=True, type=Path)
    parser.add_argument("--window-days", type=int, default=365)
    args = parser.parse_args()

    graph = json.loads(args.graph_json.read_text(encoding="utf-8"))
    milestones = load_csv(args.milestones)
    edges = build_temporal_edges(graph, milestones, args.window_days)

    args.outdir.mkdir(parents=True, exist_ok=True)
    edges_csv = args.outdir / "prepa_temporal_edges.csv"
    sector_csv = args.outdir / "prepa_temporal_sector_summary.csv"
    temporal_json = args.outdir / "prepa_temporal_graph.json"

    write_edges_csv(edges, edges_csv)
    write_sector_summary(edges, sector_csv)
    temporal_json.write_text(
        json.dumps(
            {
                "window_days": args.window_days,
                "temporal_edges": edges,
                "warning": "Temporal proximity is a prioritization signal, not proof of causation or misconduct.",
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    print(
        json.dumps(
            {
                "temporal_edges": len(edges),
                "edges_csv": str(edges_csv),
                "sector_summary": str(sector_csv),
                "temporal_json": str(temporal_json),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
