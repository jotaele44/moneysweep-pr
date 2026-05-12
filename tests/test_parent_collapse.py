"""Tests for scripts/parent_collapse.py."""
import csv
import json
from pathlib import Path

import pytest

from scripts.parent_collapse import build_entities


@pytest.fixture
def entity_repo(tmp_path):
    """Minimal repo with a few award rows including parent_uei fields."""
    processed = tmp_path / "data" / "staging" / "processed"
    processed.mkdir(parents=True)
    rows = [
        {"award_id": "A1", "recipient_name": "Acme Corp", "recipient_uei": "UEI001",
         "parent_uei": "PUEI001", "parent_name": "Acme Parent", "obligated_amount": "5000000"},
        {"award_id": "A2", "recipient_name": "Beta LLC", "recipient_uei": "UEI002",
         "parent_uei": "", "parent_name": "", "obligated_amount": "200000"},
        {"award_id": "A3", "recipient_name": "Gamma Inc", "recipient_uei": "UEI003",
         "parent_uei": "PUEI001", "parent_name": "Acme Parent", "obligated_amount": "3000000"},
    ]
    path = processed / "sample_awards.csv"
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    return tmp_path


@pytest.mark.unit
def test_build_entities_produces_entities_resolved(entity_repo):
    result = build_entities(entity_repo)
    assert result["entity_count"] >= 3
    resolved_path = entity_repo / "data" / "staging" / "processed" / "entities_resolved.csv"
    assert resolved_path.exists()
    with resolved_path.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) >= 3


@pytest.mark.unit
def test_build_entities_captures_parent_uei(entity_repo):
    build_entities(entity_repo)
    resolved_path = entity_repo / "data" / "staging" / "processed" / "entities_resolved.csv"
    with resolved_path.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    # Acme Corp + Gamma Inc have parent_uei → resolved
    resolved = [r for r in rows if r.get("parent_uei")]
    assert len(resolved) >= 2


@pytest.mark.unit
def test_build_entities_high_value_unresolved(entity_repo):
    """Entities without parent_uei and obligation ≥ $1M go to high_value_unresolved."""
    result = build_entities(entity_repo)
    # Beta LLC: $200k < $1M threshold → not in high_value
    # But Acme Corp and Gamma Inc are resolved → not in high_value
    hvu_path = entity_repo / "data" / "staging" / "processed" / "high_value_unresolved.csv"
    assert hvu_path.exists()
    # Beta LLC is $200k, so high_value_unresolved should be empty
    assert result["high_value_unresolved_count"] == 0


@pytest.mark.unit
def test_build_entities_returns_summary_keys(entity_repo):
    result = build_entities(entity_repo)
    for key in ("entity_count", "parent_resolved_count", "resolution_rate",
                "high_value_unresolved_count", "parent_conflict_count"):
        assert key in result
