"""Write project-emergence alert outputs."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from .alert_event_schema import AlertEvent
from .spiderweb_exporter import export_spiderweb_queue

DEFAULT_ALERT_DIR = (
    Path(__file__).resolve().parents[2] / "data" / "staging" / "processed" / "alerts"
)


def write_jsonl(events: list[AlertEvent], path: str | Path) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as fh:
        for event in events:
            fh.write(json.dumps(event.to_dict(), ensure_ascii=False, sort_keys=True) + "\n")


def write_csv_ledger(events: list[AlertEvent], path: str | Path) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "alert_id",
        "project_id",
        "canonical_name",
        "alert_level",
        "score",
        "source",
        "record_id",
        "record_date",
        "agency",
        "vendor",
        "amount",
        "municipio",
        "parcel_id",
        "project_stage",
        "trigger_reason",
        "confidence",
        "requires_spiderweb",
        "dedupe_key",
    ]
    with output.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for event in events:
            row = event.to_dict()
            row["trigger_reason"] = ";".join(event.trigger_reason)
            writer.writerow({field: row.get(field, "") for field in fields})


def route_alert_outputs(
    events: list[AlertEvent], alert_dir: str | Path = DEFAULT_ALERT_DIR
) -> dict[str, Any]:
    base = Path(alert_dir)
    event_path = base / "project_alert_events.jsonl"
    ledger_path = base / "project_watch_ledger.csv"
    spiderweb_path = base / "spiderweb_queue.jsonl"
    write_jsonl(events, event_path)
    write_csv_ledger(events, ledger_path)
    spiderweb_count = export_spiderweb_queue(events, spiderweb_path)
    return {
        "event_path": str(event_path),
        "ledger_path": str(ledger_path),
        "spiderweb_path": str(spiderweb_path),
        "event_count": len(events),
        "spiderweb_count": spiderweb_count,
    }
