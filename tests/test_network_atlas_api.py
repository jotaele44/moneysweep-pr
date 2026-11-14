"""Network Atlas read-only fail-closed adapter regression tests."""
import pandas as pd
import pytest
from server.backend.network_atlas import build_neighborhood


def fixture():
    return {
        "entities": pd.DataFrame([{"entity_id": "A", "name": "Alpha"},
                                  {"entity_id": "B", "name": "Beta"}]),
        "edges": pd.DataFrame([{"edge_id": "e1", "source_node_id": "A",
                                "target_node_id": "B", "edge_type": "OWNS"},
                               {"edge_id": "e2", "source_node_id": "A",
                                "target_node_id": "GHOST", "edge_type": "OWNS"}]),
    }


def test_no_unearned_evidence_promotion():
    result = build_neighborhood(fixture(), "A")
    assert result["coverage"] == "LEGACY_UNVERIFIED"
    assert result["edges"] == [{"edgeId": "e1", "sourceId": "A", "targetId": "B",
                               "predicate": "OWNS", "adjudication": "UNVERIFIED",
                               "evidence": []}]
    assert {n["entityId"] for n in result["nodes"]} == {"A", "B"}


def test_unknown_stable_id_rejected():
    with pytest.raises(KeyError):
        build_neighborhood(fixture(), "Alpha")


@pytest.mark.parametrize("limit", [0, 201, -1])
def test_invalid_budgets_rejected(limit):
    with pytest.raises(ValueError):
        build_neighborhood(fixture(), "A", limit)


def test_one_hop_not_transitive():
    data = fixture()
    data["entities"] = pd.concat([data["entities"],
        pd.DataFrame([{"entity_id": "C", "name": "Gamma"}])], ignore_index=True)
    data["edges"] = pd.concat([data["edges"],
        pd.DataFrame([{"edge_id": "e3", "source_node_id": "B",
                       "target_node_id": "C", "edge_type": "OWNS"}])], ignore_index=True)
    result = build_neighborhood(data, "A")
    assert "C" not in {n["entityId"] for n in result["nodes"]}


def test_limit_and_truncation():
    data = fixture()
    data["edges"] = pd.concat([data["edges"],
        pd.DataFrame([{"edge_id": "e3", "source_node_id": "B",
                       "target_node_id": "A", "edge_type": "OWNS"}])], ignore_index=True)
    result = build_neighborhood(data, "A", 1)
    assert result["truncated"] is True
    assert len(result["edges"]) == 1
