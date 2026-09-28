import json

import pandas as pd

from moneysweep.political_finance.flow_graph import (
    build_political_finance_graph,
    classify_committee,
    find_flow_paths,
    normalize_name,
)


def test_classify_committee_types():
    assert classify_committee({"committee_type": "O"}) == "SUPER_PAC"
    assert classify_committee({"committee_type": "X"}) == "PARTY_COMMITTEE"
    assert (
        classify_committee({"committee_type_full": "Joint fundraising committee"})
        == "JOINT_FUNDRAISING_COMMITTEE"
    )
    assert classify_committee({"organization_type": "527 organization"}) == "POLITICAL_527"


def test_unique_name_candidate_does_not_resolve_identity():
    committees = pd.DataFrame(
        [{"committee_id": "C1", "name": "Committee One", "committee_type": "O"}]
    )
    disbursements = pd.DataFrame(
        [
            {
                "committee_id": "C1",
                "committee_name": "Committee One",
                "recipient_name": "Acme, Inc.",
                "disbursement_amount": "2500",
                "disbursement_date": "2026-01-15",
                "transaction_id": "TX1",
            }
        ]
    )
    awards = pd.DataFrame([{"awardee_id": "A1", "awardee_name": "ACME INC"}])

    graph = build_political_finance_graph(
        committees=committees,
        disbursements=disbursements,
        entity_frames=[("awards", awards)],
    )

    resolution = graph["resolutions"].iloc[0]
    assert resolution["resolved_entity_id"] == ""
    assert resolution["resolution_method"] == "name_candidate_only"
    assert resolution["identity_state"] == "CANDIDATE_NOT_IDENTITY"
    assert json.loads(resolution["candidate_entity_ids"]) == ["awards:A1"]
    assert graph["edges"].empty


def test_authoritative_fec_recipient_id_can_bind_and_emit_edge():
    committees = pd.DataFrame(
        [
            {"committee_id": "C1", "name": "Committee One", "committee_type": "O"},
            {"committee_id": "C2", "name": "Committee Two", "committee_type": "H"},
        ]
    )
    disbursements = pd.DataFrame(
        [
            {
                "committee_id": "C1",
                "committee_name": "Committee One",
                "recipient_committee_id": "C2",
                "recipient_name": "Display Name",
                "disbursement_amount": "2500",
                "disbursement_date": "2026-01-15",
                "transaction_id": "TX1",
            }
        ]
    )

    graph = build_political_finance_graph(
        committees=committees,
        disbursements=disbursements,
    )

    resolution = graph["resolutions"].iloc[0]
    assert resolution["resolved_entity_id"] == "fec_committee:C2"
    assert resolution["resolution_method"] == "authoritative_fec_id"
    assert resolution["identity_state"] == "AUTHORITATIVE_ID"
    edge = graph["edges"].iloc[0]
    assert edge["edge_type"] == "DISBURSED_TO"
    assert edge["target_entity_id"] == "fec_committee:C2"
    assert edge["provenance"] == "fec_schedule_b:TX1"


def test_ambiguous_name_candidates_are_preserved_for_review():
    disbursements = pd.DataFrame(
        [{"committee_id": "C1", "recipient_name": "ACME", "transaction_id": "T1"}]
    )
    entities = pd.DataFrame(
        [
            {"entity_id": "1", "canonical_name": "ACME"},
            {"entity_id": "2", "canonical_name": "ACME"},
        ]
    )

    graph = build_political_finance_graph(
        disbursements=disbursements,
        entity_frames=[("resolved", entities)],
    )

    row = graph["resolutions"].iloc[0]
    assert bool(row["review_required"])
    assert row["resolution_method"] == "name_candidate_only"
    assert row["identity_state"] == "CANDIDATE_NOT_IDENTITY"
    assert json.loads(row["candidate_entity_ids"]) == ["resolved:1", "resolved:2"]


def test_name_only_donor_is_not_promoted_to_graph_entity_or_edge():
    contributions = pd.DataFrame(
        [
            {
                "contributor_name": "Donor A",
                "committee_id": "C1",
                "committee_name": "Committee",
                "amount": "100",
                "transaction_id": "R1",
            }
        ]
    )
    committees = pd.DataFrame([{"committee_id": "C1", "name": "Committee"}])

    graph = build_political_finance_graph(
        contributions=contributions,
        committees=committees,
    )

    assert not (graph["entities"]["entity_type"] == "DONOR").any()
    assert graph["edges"].empty


def test_stable_donor_and_authoritative_committee_ids_support_paths():
    contributions = pd.DataFrame(
        [
            {
                "contributor_id": "D1",
                "contributor_name": "Donor A",
                "committee_id": "C1",
                "committee_name": "Committee One",
                "amount": "100",
                "transaction_id": "R1",
            }
        ]
    )
    committees = pd.DataFrame(
        [
            {"committee_id": "C1", "name": "Committee One"},
            {"committee_id": "C2", "name": "Committee Two"},
        ]
    )
    disbursements = pd.DataFrame(
        [
            {
                "committee_id": "C1",
                "committee_name": "Committee One",
                "recipient_committee_id": "C2",
                "recipient_name": "Committee Two",
                "disbursement_amount": "80",
                "transaction_id": "D1",
            }
        ]
    )

    graph = build_political_finance_graph(
        contributions=contributions,
        committees=committees,
        disbursements=disbursements,
    )

    assert not graph["edges"]["edge_id"].duplicated().any()
    donor = graph["entities"].loc[
        graph["entities"]["entity_type"] == "DONOR", "entity_id"
    ].iloc[0]
    paths = find_flow_paths(graph["edges"], donor, max_hops=4)
    assert paths["hop_count"].max() == 2
    assert normalize_name("Acme, Inc.") == "ACME INC"


def test_schedule_e_requires_candidate_id_not_candidate_name():
    committees = pd.DataFrame([{"committee_id": "C1", "name": "Committee One"}])
    expenditures = pd.DataFrame(
        [
            {
                "committee_id": "C1",
                "candidate_name": "NAME ONLY",
                "transaction_id": "E0",
                "expenditure_amount": "10",
            },
            {
                "committee_id": "C1",
                "candidate_id": "H1",
                "candidate_name": "Candidate One",
                "transaction_id": "E1",
                "expenditure_amount": "20",
            },
        ]
    )

    graph = build_political_finance_graph(
        committees=committees,
        independent_expenditures=expenditures,
    )

    assert len(graph["edges"]) == 1
    assert graph["edges"].iloc[0]["target_entity_id"] == "fec_candidate:H1"
