from __future__ import annotations

import pandas as pd
import pytest

from server.backend.leaderboards import _competition_ranks, _contract_award_ranking


def _data():
    return {
        "contracts": pd.DataFrame([
            {"contract_id":"c1","contractor_entity_id":"e1","awarding_entity_id":"a1","award_amount":"100","currency":"USD","start_date":"2025-01-01","source_id":"s1","source_ref":"r1"},
            {"contract_id":"c2","contractor_entity_id":"e1","awarding_entity_id":"a1","award_amount":"50","currency":"USD","start_date":"2025-02-01","source_id":"s2","source_ref":"r2"},
            {"contract_id":"c3","contractor_entity_id":"e2","awarding_entity_id":"a1","award_amount":"150","currency":"USD","start_date":"2025-03-01","source_id":"s1","source_ref":"r3"},
            {"contract_id":"c4","contractor_entity_id":"e3","awarding_entity_id":"a1","award_amount":"","currency":"USD","start_date":"2025-04-01","source_id":"s1","source_ref":"r4"},
            {"contract_id":"c5","contractor_entity_id":"","awarding_entity_id":"a1","award_amount":"999","currency":"USD","start_date":"2025-05-01","source_id":"s1","source_ref":"r5"},
        ]),
        "entities": pd.DataFrame([
            {"entity_id":"e1","name":"Entity One","entity_type":"Company"},
            {"entity_id":"e2","name":"Entity Two","entity_type":"Company"},
            {"entity_id":"e3","name":"Entity Three","entity_type":"Company"},
            {"entity_id":"a1","name":"Agency","entity_type":"Agency"},
        ]),
        "edges": pd.DataFrame([
            {"edge_type":"LOCATED_IN","source_node_id":"e1","target_node_id":"m1"},
            {"edge_type":"LOCATED_IN","source_node_id":"e2","target_node_id":"m1"},
            {"edge_type":"LOCATED_IN","source_node_id":"e2","target_node_id":"m2"},
        ]),
        "municipalities": pd.DataFrame([
            {"municipality_id":"m1","name":"San Juan"},
            {"municipality_id":"m2","name":"Ponce"},
        ]),
    }


@pytest.mark.unit
def test_competition_ranking_preserves_ties():
    rows = _competition_ranks([
        {"entityId":"b","metricValue":10.0},
        {"entityId":"a","metricValue":10.0},
        {"entityId":"c","metricValue":5.0},
    ])
    assert [(r["entityId"], r["rank"]) for r in rows] == [("a", 1), ("b", 1), ("c", 3)]


@pytest.mark.unit
def test_ranking_closes_accounting_and_never_name_groups():
    result = _contract_award_ranking(_data(), limit=25, start_year=None, end_year=None, municipality=None, entity_type=None, currency="USD")
    assert result["accounting"]["arithmeticClosed"] is True
    assert result["accounting"]["retainedRecords"] == 3
    assert result["accounting"]["excludedRecords"] == 1
    assert result["accounting"]["unresolvedRecords"] == 1
    assert [(r["entityId"], r["metricValue"], r["rank"]) for r in result["rows"]] == [
        ("e1", 150.0, 1), ("e2", 150.0, 1)
    ]
    assert all(r["entityResolutionState"] == "CANONICAL_V1_ENTITY_ID" for r in result["rows"])


@pytest.mark.unit
def test_municipality_filter_fails_closed_on_multi_location_identity():
    result = _contract_award_ranking(_data(), limit=25, start_year=None, end_year=None, municipality="San Juan", entity_type=None, currency="USD")
    assert [r["entityId"] for r in result["rows"]] == ["e1"]
    assert result["accounting"]["unresolvedRecords"] >= 1
    assert result["accounting"]["arithmeticClosed"] is True
