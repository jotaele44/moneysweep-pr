from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from server.backend import leaderboard_adapters as adapters


ROOT = Path(__file__).resolve().parents[1]
ONTOLOGY = ROOT / "config" / "financial_category_ontology.json"


def _core():
    return {
        "contracts": pd.DataFrame(columns=["contract_id", "contractor_entity_id", "awarding_entity_id", "award_amount", "currency", "start_date"]),
        "entities": pd.DataFrame([
            {"entity_id": "e1", "name": "Issuer One", "entity_type": "agency"},
            {"entity_id": "e2", "name": "Issuer Two", "entity_type": "agency"},
        ]),
        "edges": pd.DataFrame(columns=["edge_type", "source_node_id", "target_node_id"]),
        "municipalities": pd.DataFrame(columns=["municipality_id", "name"]),
    }


@pytest.mark.unit
def test_ontology_adapter_denominator_is_explicit_and_closed():
    ontology = json.loads(ONTOLOGY.read_text(encoding="utf-8"))
    categories = ontology["categories"]
    assert categories
    ids = [item["id"] for item in categories]
    assert len(ids) == len(set(ids))
    for item in categories:
        assert item.get("metric_type")
        assert item.get("certification_state")
        assert item.get("reason")
        adapter = item.get("adapter")
        if adapter:
            assert adapter in adapters.ADAPTERS
        else:
            assert item["certification_state"] in {
                "OPEN", "OPEN_NOT_MATERIALIZED", "CANDIDATE_NOT_IDENTITY", "BLOCKED", "UNRESOLVED"
            }


@pytest.mark.unit
def test_debt_par_is_separate_measure(monkeypatch):
    debt = pd.DataFrame([
        {"issuer_entity_id": "e1", "par_amount": "100", "currency": "USD", "issue_year": "2025", "debt_class": "GO", "evidence_id": "ev1"},
        {"issuer_entity_id": "e1", "par_amount": "50", "currency": "USD", "issue_year": "2026", "debt_class": "GO", "evidence_id": "ev2"},
        {"issuer_entity_id": "e2", "par_amount": "80", "currency": "USD", "issue_year": "2026", "debt_class": "REV", "evidence_id": "ev3"},
    ])
    original = adapters._read
    monkeypatch.setattr(adapters, "_read", lambda path: debt if path.name == "debt_instruments.csv" else original(path))
    monkeypatch.setattr(adapters, "_manifest", lambda path: {"path": path.name, "sha256": "a" * 64, "bytes": 1, "modifiedAt": "x"})
    result = adapters.debt_issuance(_core(), limit=25, start_year=None, end_year=None, municipality=None, entity_type=None, currency="USD")
    assert result["metricType"] == "DEBT_ISSUED_PAR"
    assert result["rows"][0]["entityId"] == "e1"
    assert result["rows"][0]["metricValue"] == 150
    assert "outstanding debt" in result["methodology"]["nonEquivalence"]


@pytest.mark.unit
def test_federal_award_missing_uei_is_unresolved(monkeypatch, tmp_path):
    frame = pd.DataFrame([
        {"recipient_uei": "UEI1", "recipient_name": "One", "obligated_amount": "100", "fiscal_year": "2025", "source_dataset": "contracts", "award_category": "contract"},
        {"recipient_uei": "", "recipient_name": "Name Only", "obligated_amount": "500", "fiscal_year": "2025", "source_dataset": "contracts", "award_category": "contract"},
    ])
    fake = tmp_path / "pr_all_awards_master.csv"
    fake.write_text("placeholder")
    monkeypatch.setattr(adapters, "PROCESSED", tmp_path)
    monkeypatch.setattr(adapters, "_read", lambda path: frame if path.name == "pr_all_awards_master.csv" else pd.DataFrame())
    monkeypatch.setattr(adapters, "_manifest", lambda path: {"path": path.name, "sha256": "a" * 64, "bytes": 1, "modifiedAt": "x"})
    result = adapters.federal_contract_obligations(_core(), limit=25, start_year=None, end_year=None, municipality=None, entity_type=None, currency="USD")
    assert result["accounting"]["unresolvedRecords"] == 1
    assert [row["entityId"] for row in result["rows"]] == ["uei:UEI1"]


@pytest.mark.unit
def test_federal_contract_and_grant_filters_do_not_mix(monkeypatch, tmp_path):
    frame = pd.DataFrame([
        {"recipient_uei": "UEI1", "recipient_name": "One", "obligated_amount": "100", "fiscal_year": "2025", "source_dataset": "contracts", "award_category": "contract"},
        {"recipient_uei": "UEI1", "recipient_name": "One", "obligated_amount": "900", "fiscal_year": "2025", "source_dataset": "grants", "award_category": "grant"},
    ])
    (tmp_path / "pr_all_awards_master.csv").write_text("placeholder")
    monkeypatch.setattr(adapters, "PROCESSED", tmp_path)
    monkeypatch.setattr(adapters, "_read", lambda path: frame if path.name == "pr_all_awards_master.csv" else pd.DataFrame())
    monkeypatch.setattr(adapters, "_manifest", lambda path: {"path": path.name, "sha256": "a" * 64, "bytes": 1, "modifiedAt": "x"})
    contracts = adapters.federal_contract_obligations(_core(), limit=25, start_year=None, end_year=None, municipality=None, entity_type=None, currency="USD")
    grants = adapters.federal_grants(_core(), limit=25, start_year=None, end_year=None, municipality=None, entity_type=None, currency="USD")
    assert contracts["rows"][0]["metricValue"] == 100
    assert grants["rows"][0]["metricValue"] == 900


@pytest.mark.unit
def test_campaign_name_derived_committee_identity_is_not_ranked(monkeypatch, tmp_path):
    edges = pd.DataFrame([
        {"edge_type": "CONTRIBUTED_TO", "target_entity_id": "C001", "amount": "100", "transaction_date": "2025-01-01", "source_dataset": "fec_schedule_a"},
        {"edge_type": "CONTRIBUTED_TO", "target_entity_id": "namehash", "amount": "999", "transaction_date": "2025-01-01", "source_dataset": "oce"},
    ])
    committees = pd.DataFrame([
        {"committee_entity_id": "C001", "fec_committee_id": "C001", "canonical_name": "Authoritative"},
        {"committee_entity_id": "namehash", "fec_committee_id": "", "canonical_name": "Name Derived"},
    ])
    (tmp_path / "pr_campaign_finance_edges.csv").write_text("placeholder")
    (tmp_path / "pr_campaign_finance_committees.csv").write_text("placeholder")
    monkeypatch.setattr(adapters, "PROCESSED", tmp_path)
    monkeypatch.setattr(adapters, "_read", lambda path: edges if path.name.endswith("edges.csv") else committees)
    monkeypatch.setattr(adapters, "_manifest", lambda path: {"path": path.name, "sha256": "a" * 64, "bytes": 1, "modifiedAt": "x"})
    result = adapters.campaign_contributions_received(_core(), limit=25, start_year=None, end_year=None, municipality=None, entity_type=None, currency="USD")
    assert [row["entityId"] for row in result["rows"]] == ["fec_committee:C001"]
    assert result["accounting"]["unresolvedRecords"] == 1
