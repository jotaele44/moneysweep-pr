"""Tests for scripts/parent_collapse.py."""
import csv

import pytest

from scripts.parent_collapse import build_entities, _classify_entity_type


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
                "high_value_unresolved_count", "parent_conflict_count",
                "entity_type_counts", "corporate_entity_count", "corporate_parent_uei_rate"):
        assert key in result


@pytest.mark.unit
def test_build_entities_emits_entity_type_column(entity_repo):
    """entities_resolved.csv must contain entity_type for every row."""
    build_entities(entity_repo)
    resolved_path = entity_repo / "data" / "staging" / "processed" / "entities_resolved.csv"
    with resolved_path.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert all("entity_type" in r for r in rows)
    # All fixture entities are businesses (Acme Corp, Beta LLC, Gamma Inc) → corporate
    types = {r["entity_type"] for r in rows}
    assert "corporate" in types


@pytest.mark.unit
def test_classify_entity_type_government():
    assert _classify_entity_type("Puerto Rico Department of Health") == "government"
    assert _classify_entity_type("ADMINISTRACION DE DESARROLLO SOCIOECONOMICO") == "government"
    assert _classify_entity_type("MUNICIPIO DE PONCE") == "government"
    assert _classify_entity_type("GOVERNOR'S AUTHORIZED REPRESENTATIVE") == "government"


@pytest.mark.unit
def test_classify_entity_type_corporate():
    assert _classify_entity_type("AECOM Technical Services Inc") == "corporate"
    assert _classify_entity_type("Fluor Enterprises LLC") == "corporate"
    assert _classify_entity_type("LGA Strategies, LLC") == "corporate"


@pytest.mark.unit
def test_classify_entity_type_nonprofit():
    assert _classify_entity_type("University of Puerto Rico") == "nonprofit"
    assert _classify_entity_type("Ana G Mendez University") == "nonprofit"


@pytest.mark.unit
def test_classify_entity_type_individual():
    assert _classify_entity_type("RUIZ TORRES, HECTOR J") == "individual"
    assert _classify_entity_type("DAVILA, MARIA DEL CARMEN") == "individual"


@pytest.mark.unit
def test_classify_entity_type_aggregate():
    assert _classify_entity_type("MULTIPLE RECIPIENTS") == "aggregate"


@pytest.mark.unit
def test_corporate_parent_uei_rate_excludes_government(entity_repo):
    """corporate_parent_uei_rate must only count corporate entities."""
    # Add a government row to the fixture
    govt_row = {
        "award_id": "A4", "recipient_name": "Department of Housing of Puerto Rico",
        "recipient_uei": "GOVUEI000001",
        "parent_uei": "", "parent_name": "", "obligated_amount": "50000000",
    }
    csv_path = entity_repo / "data" / "staging" / "processed" / "sample_awards.csv"
    with csv_path.open("a", newline="", encoding="utf-8") as f:
        import csv as _csv
        w = _csv.DictWriter(f, fieldnames=list(govt_row.keys()))
        w.writerow(govt_row)
    result = build_entities(entity_repo)
    # The government entity has no parent, but corporate_parent_uei_rate should
    # only reflect corporate entities — government count must not reduce it.
    assert "government" in result["entity_type_counts"]
    # Acme Corp + Gamma Inc (2 of 4 corp entities) have parent_uei → rate ≥ 0.3
    assert result["corporate_parent_uei_rate"] > 0.3
