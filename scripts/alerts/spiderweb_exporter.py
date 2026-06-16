"""Export review-plus alert events as Spiderweb seed packets."""

from __future__ import annotations

import json
from pathlib import Path

from .alert_event_schema import AlertEvent


def build_spiderweb_packet(event: AlertEvent) -> dict:
    seeds = [event.canonical_name, event.vendor, event.agency, event.municipio]
    seeds = [s for s in seeds if s]
    return {
        "project_id": event.project_id,
        "alert_id": event.alert_id,
        "seed_entities": sorted(set(seeds)),
        "seed_addresses": [],
        "seed_people": [],
        "seed_sources": [event.source] if event.source else [],
        "reason": "review_threshold_crossed",
        "minimum_graph_depth": 2,
    }


def export_spiderweb_queue(events: list[AlertEvent], output_path: str | Path) -> int:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    packets = [build_spiderweb_packet(e) for e in events if e.requires_spiderweb]
    with output.open("w", encoding="utf-8") as fh:
        for packet in packets:
            fh.write(json.dumps(packet, ensure_ascii=False, sort_keys=True) + "\n")
    return len(packets)
