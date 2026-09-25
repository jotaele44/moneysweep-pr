from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "schemas" / "government_organization_change_events.schema.json"
EVENTS = ROOT / "data" / "derived" / "government_organization_change_events.json"
CANDIDATES = (
    ROOT / "data" / "staging" / "processed" / "government_organization_change_candidates.json"
)


def test_government_change_schema_parses_and_preserves_temporal_identity_controls() -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    props = schema["properties"]

    assert "Succession is evidence-bearing" in schema["description"]
    assert "rename alone never establishes succession" in schema["description"]
    assert "effective_date" in props
    assert "predecessor_entities" in props
    assert "successor_entities" in props
    assert {"PASS", "FAIL", "OPEN", "BLOCKED", "PROVISIONAL", "UNRESOLVED", "SUPERSEDED"} <= set(
        props["certification_state"]["enum"]
    )


def test_current_government_change_ledgers_remain_bounded_empty_state() -> None:
    events = json.loads(EVENTS.read_text(encoding="utf-8"))
    candidates = json.loads(CANDIDATES.read_text(encoding="utf-8"))

    assert events["schema_version"] == "government_organization_change_events_v1"
    assert events["events"] == []
    assert candidates["scope_claim"] == "BOUNDED_NOT_EXHAUSTIVE"
    assert candidates["candidates"] == []
