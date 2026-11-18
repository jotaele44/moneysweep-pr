import json

import pandas as pd
import pytest

from scripts import build_campaign_finance_entities as mod


def _processed(tmp_path):
    processed = tmp_path / "data" / "staging" / "processed"
    processed.mkdir(parents=True)
    return processed


@pytest.mark.unit
def test_name_only_recipient_is_candidate_not_identity(tmp_path):
    processed = _processed(tmp_path)
    pd.DataFrame(
        [
            {
                "cycle": "2024",
                "contributor_name": "DONOR X",
                "contribution_receipt_amount": "100",
                "contribution_receipt_date": "2024-01-01",
                "committee_id": "C1",
                "committee_name": "FRIENDS OF X",
                "candidate_id": "H1",
                "candidate_name": "CANDIDATE X",
                "is_individual": "False",
            }
        ]
    ).to_csv(processed / "pr_fec_contributions.csv", index=False)
    pd.DataFrame(
        [{"committee_id": "C1", "name": "FRIENDS OF X", "committee_type": "H", "state": "PR"}]
    ).to_csv(processed / "pr_fec_committees.csv", index=False)
    pd.DataFrame(
        [
            {
                "cycle": "2024",
                "committee_id": "C1",
                "committee_name": "FRIENDS OF X",
                "recipient_name": "CANDIDATE X",
                "disbursement_amount": "50",
                "disbursement_date": "2024-02-01",
            }
        ]
    ).to_csv(processed / "pr_fec_disbursements.csv", index=False)
    pd.DataFrame(columns=["committee_id", "candidate_id", "expenditure_amount"]).to_csv(
        processed / "pr_fec_independent_expenditures.csv", index=False
    )

    result = mod.run(root=tmp_path)

    assert result["candidates"] == 1
    assert result["committees"] == 1
    assert result["recipients"] == 1
    assert result["resolved_recipients"] == 0
    rec = pd.read_csv(processed / "pr_campaign_finance_recipient_resolution.csv")
    assert rec.iloc[0]["resolved_entity_type"] == "unresolved"
    assert rec.iloc[0]["match_method"] == "name_candidate_only"
    assert rec.iloc[0]["identity_state"] == "CANDIDATE_NOT_IDENTITY"
    candidates = json.loads(rec.iloc[0]["candidate_set"])
    assert {item["entity_id"] for item in candidates} == {"H1"}


@pytest.mark.unit
def test_authoritative_recipient_committee_id_can_resolve(tmp_path):
    processed = _processed(tmp_path)
    pd.DataFrame(columns=["candidate_id", "candidate_name"]).to_csv(
        processed / "pr_fec_contributions.csv", index=False
    )
    pd.DataFrame(
        [
            {"committee_id": "C1", "name": "COMMITTEE ONE", "committee_type": "H", "state": "PR"},
            {"committee_id": "C2", "name": "COMMITTEE TWO", "committee_type": "H", "state": "PR"},
        ]
    ).to_csv(processed / "pr_fec_committees.csv", index=False)
    pd.DataFrame(
        [
            {
                "committee_id": "C1",
                "committee_name": "COMMITTEE ONE",
                "recipient_committee_id": "C2",
                "recipient_name": "A DISPLAY NAME THAT NEED NOT MATCH",
                "disbursement_amount": "50",
            }
        ]
    ).to_csv(processed / "pr_fec_disbursements.csv", index=False)
    pd.DataFrame(columns=["committee_id", "candidate_id"]).to_csv(
        processed / "pr_fec_independent_expenditures.csv", index=False
    )

    result = mod.run(root=tmp_path)
    rec = pd.read_csv(processed / "pr_campaign_finance_recipient_resolution.csv")

    assert result["resolved_recipients"] == 1
    assert rec.iloc[0]["resolved_entity_id"] == "C2"
    assert rec.iloc[0]["match_method"] == "authoritative_recipient_id"
    assert rec.iloc[0]["identity_state"] == "AUTHORITATIVE_ID"


@pytest.mark.unit
def test_idless_oce_name_is_not_promoted_to_canonical_entity(tmp_path):
    processed = _processed(tmp_path)
    pd.DataFrame(columns=["candidate_id", "candidate_name"]).to_csv(
        processed / "pr_fec_contributions.csv", index=False
    )
    pd.DataFrame(columns=["committee_id", "name"]).to_csv(
        processed / "pr_fec_committees.csv", index=False
    )
    pd.DataFrame(
        [
            {
                "candidate_or_committee": "LOCAL NAME ONLY",
                "party": "X",
                "office_sought": "Mayor",
                "cycle": "2024",
            }
        ]
    ).to_csv(processed / "pr_oce_donations.csv", index=False)
    pd.DataFrame(columns=["recipient_name"]).to_csv(
        processed / "pr_fec_disbursements.csv", index=False
    )
    pd.DataFrame(columns=["committee_id", "candidate_id"]).to_csv(
        processed / "pr_fec_independent_expenditures.csv", index=False
    )

    result = mod.run(root=tmp_path)

    assert result["candidates"] == 0
    assert result["committees"] == 0
    assert pd.read_csv(processed / "pr_campaign_finance_candidates.csv").empty
    assert pd.read_csv(processed / "pr_campaign_finance_committees.csv").empty


@pytest.mark.unit
def test_graph_edges_require_authoritative_endpoint_ids(tmp_path):
    processed = _processed(tmp_path)
    pd.DataFrame(
        [
            {
                "cycle": "2024",
                "contributor_name": "NAME ONLY DONOR",
                "committee_id": "C1",
                "committee_name": "COMMITTEE ONE",
                "candidate_id": "H1",
                "candidate_name": "CANDIDATE ONE",
            }
        ]
    ).to_csv(processed / "pr_fec_contributions.csv", index=False)
    pd.DataFrame(
        [
            {"committee_id": "C1", "name": "COMMITTEE ONE"},
            {"committee_id": "C2", "name": "COMMITTEE TWO"},
        ]
    ).to_csv(processed / "pr_fec_committees.csv", index=False)
    pd.DataFrame(
        [
            {
                "committee_id": "C1",
                "recipient_committee_id": "C2",
                "disbursement_amount": "25",
                "transaction_id": "B1",
            }
        ]
    ).to_csv(processed / "pr_fec_disbursements.csv", index=False)
    pd.DataFrame(
        [
            {
                "committee_id": "C1",
                "candidate_id": "H1",
                "candidate_name": "CANDIDATE ONE",
                "expenditure_amount": "100",
                "transaction_id": "E1",
                "support_oppose_indicator": "S",
            }
        ]
    ).to_csv(processed / "pr_fec_independent_expenditures.csv", index=False)

    mod.run(root=tmp_path)
    edges = pd.read_csv(processed / "pr_campaign_finance_edges.csv")

    assert set(edges["source_dataset"]) == {"fec_schedule_b", "fec_schedule_e"}
    assert set(edges["edge_type"]) == {"TRANSFERRED_TO", "SUPPORTED"}
    assert "fec_schedule_a" not in set(edges["source_dataset"])
    assert set(edges["confidence"]) == {100}
