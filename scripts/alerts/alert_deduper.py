"""Stable deduplication keys for alert events."""
from __future__ import annotations

import hashlib
from typing import Any


def build_dedupe_key(project_id: str, record: dict[str, Any]) -> str:
    parts = [
        project_id,
        str(record.get("record_id") or record.get("award_id") or record.get("id") or ""),
        str(record.get("source_dataset") or record.get("source") or ""),
        str(record.get("award_date") or record.get("record_date") or ""),
        str(record.get("recipient_name") or record.get("vendor") or ""),
        str(record.get("obligated_amount") or record.get("amount") or ""),
        str(record.get("description") or record.get("title") or "")[:240],
    ]
    raw = "|".join(parts).lower().strip()
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def dedupe_events(events):
    seen = set()
    unique = []
    for event in events:
        key = getattr(event, "dedupe_key", "") or event.alert_id
        if key in seen:
            continue
        seen.add(key)
        unique.append(event)
    return unique
