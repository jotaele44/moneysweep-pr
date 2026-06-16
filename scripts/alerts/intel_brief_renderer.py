"""Markdown intel brief renderer for project-emergence alerts."""
from __future__ import annotations

from pathlib import Path

from .alert_event_schema import AlertEvent


def render_intel_brief(event: AlertEvent) -> str:
    reasons = "\n".join(f"| {reason} | yes |" for reason in event.trigger_reason)
    return f"""# Project Alert Brief: {event.canonical_name}

## Alert level
{event.alert_level}

## Trigger summary
Contract Sweeper detected a {event.alert_level} project-emergence signal for `{event.project_id}` with score `{event.score}`.

## Source records
| Field | Value |
|---|---|
| Source | {event.source} |
| Record ID | {event.record_id} |
| Record date | {event.record_date} |
| Agency | {event.agency} |
| Vendor | {event.vendor} |
| Amount | {event.amount} |
| Municipio | {event.municipio} |

## Signal table
| Signal | Present |
|---|---|
{reasons or '| none | no |'}

## Entity graph summary
Spiderweb required: `{event.requires_spiderweb}`.

## Geographic anchor
Municipio: `{event.municipio}`. Parcel/facility: `{event.parcel_id}`.

## Confidence
{event.confidence}

## Contradictions / false-positive controls
Deduplication key: `{event.dedupe_key}`. Review common-word collisions, stale mirrors, and media-only references before escalation.

## Next actions
Pull the source record, verify agency/vendor identity, and run Spiderweb if the alert is review-plus.
"""


def export_intel_brief(event: AlertEvent, output_dir: str | Path) -> Path:
    path = Path(output_dir) / f"{event.project_id}_{event.alert_id}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_intel_brief(event), encoding="utf-8")
    return path
