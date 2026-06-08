"""Tests for scripts/alias_registry_builder.py."""

import csv
import json

import pytest

from scripts.alias_registry_builder import build_alias_registry


@pytest.fixture
def alias_repo(tmp_path):
    """Repo with sample contracts CSV containing variant entity names."""
    processed = tmp_path / "data" / "staging" / "processed"
    processed.mkdir(parents=True)
    rows = [
        {"award_id": "A1", "recipient_name": "LGA Strategies, LLC", "obligated_amount": "500000"},
        {"award_id": "A2", "recipient_name": "LGA Strategies LLC", "obligated_amount": "300000"},
        {
            "award_id": "A3",
            "recipient_name": "Autopistas Metropolitanas de Puerto Rico LLC",
            "obligated_amount": "10000000",
        },
        {
            "award_id": "A4",
            "recipient_name": "Ferrovial Agroman, S.A.",
            "obligated_amount": "2000000",
        },
        {"award_id": "A5", "recipient_name": "Brown & Sons Inc", "obligated_amount": "100000"},
    ]
    path = processed / "sample_contracts.csv"
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    return tmp_path


@pytest.mark.unit
def test_build_alias_registry_creates_json(alias_repo):
    build_alias_registry(alias_repo)
    out_path = alias_repo / "data" / "staging" / "processed" / "enrichment" / "alias_registry.json"
    assert out_path.exists()
    data = json.loads(out_path.read_text())
    assert data["entry_count"] > 0


@pytest.mark.unit
def test_alias_registry_clusters_variant_spellings(alias_repo):
    """LGA Strategies, LLC and LGA Strategies LLC should cluster together."""
    result = build_alias_registry(alias_repo)
    entries_by_norm = {e["normalized_name"]: e for e in result["entries"]}
    assert "LGA STRATEGIES" in entries_by_norm
    lga = entries_by_norm["LGA STRATEGIES"]
    assert lga["row_count"] == 2
    assert lga["manual_review_required"] is True  # >1 alias


@pytest.mark.unit
def test_alias_registry_normalizes_dotted_suffix(alias_repo):
    """Ferrovial Agroman, S.A. → normalized FERROVIAL AGROMAN."""
    result = build_alias_registry(alias_repo)
    norms = {e["normalized_name"] for e in result["entries"]}
    assert "FERROVIAL AGROMAN" in norms


@pytest.mark.unit
def test_alias_registry_identity_warning_present(alias_repo):
    result = build_alias_registry(alias_repo)
    assert "identity_warning" in result
    assert "not verified" in result["identity_warning"].lower()
