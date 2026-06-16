"""Render GitHub issue bodies for project-emergence alerts.

This module deliberately does not call the GitHub API. It emits deterministic
Markdown that can be handed to CI, a CLI, or a connector-specific action.
"""
from __future__ import annotations

from .alert_event_schema import AlertEvent


def issue_title(event: AlertEvent) -> str:
    return f"[PROJECT ALERT][{event.alert_level.upper()}] {event.canonical_name} — {', '.join(event.trigger_reason[:2])}"


def issue_labels(event: AlertEvent) -> list[str]:
    labels = ["alert", "project-watch", event.alert_level, f"project:{event.project_id}"]
    if event.requires_spiderweb:
        labels.append("requires-spiderweb")
    if event.source:
        labels.append(f"source:{event.source}")
    return labels


def issue_body(event: AlertEvent) -> str:
    reasons = "\n".join(f"- {reason}" for reason in event.trigger_reason) or "- no trigger reason recorded"
    return f"""## Project
{event.canonical_name}

## Alert level
{event.alert_level}

## Score
{event.score} / 100

## Why this triggered
{reasons}

## Source record
- Source: {event.source}
- Record ID: {event.record_id}
- Date: {event.record_date}
- Agency: {event.agency}
- Vendor: {event.vendor}
- Amount: {event.amount}
- Municipio: {event.municipio}

## Required next step
{'Run Spiderweb enrichment for seed entities.' if event.requires_spiderweb else 'Store in watch ledger; no Spiderweb run required.'}
"""
