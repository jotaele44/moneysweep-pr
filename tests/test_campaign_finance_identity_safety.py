from __future__ import annotations

import json

import pandas as pd
import pytest

from scripts import build_campaign_finance_entities_certified as builder
from scripts import validate_campaign_finance_materialization_certified as validator

pytestmark = pytest.mark.unit


def _write_fixture(root) -> None:
    processed = root / "data" / "staging" / "processed"
    processed.mkdir(parents=True, exist_ok=True)
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
                "transaction_id": "TX-A-1",
            }
        ]
    ).to_csv(processed / "pr_fec_contributions.csv", index=False)
    pd.DataFrame(
        [
            {
                "committee_id": "C1",
                "name": "FRIENDS OF X",
                "committee_type": "H",
                "state": "PR",
            }
        ]
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
    pd.DataFrame(
        [
            {
                "committee_id": "C1",
                "candidate_id": "",
                "candidate_name": "CANDIDATE X",
                "expenditure_amount": "75",
                "expenditure_date": "2024-03-01",
                "support_oppose_indicator": "S",
                "cycle": "2024",
                "transaction_id": "TX-E-1",
            },
            {
                "committee_id": "C1",
                "candidate_id": "H1",
                "candidate_name": "CANDIDATE X",
                "expenditure_amount": "125",
                "expenditure_date": "2024-03-02",
                "support_oppose_indicator": "S",
                "cycle": "2024",
                "transaction_id": "TX-E-2",
            },
        ]
    ).to_csv(processed / "pr_fec_independent_expenditures.csv", index=False)


def test_normalized_name_is_candidate_discovery_not_identity(tmp_path) -> None:
    _write_fixture(tmp_path)
    result = builder.run(root=tmp_path)

    assert result["resolved_recipients"] == 0
    assert result["recipient_candidate_sets"] == 1

    processed = tmp_path / "data" / "staging" / "processed"
    recipients = pd.read_csv(
        processed / "pr_campaign_finance_recipient_resolution.csv",
        dtype=str,
        keep_default_na=False,
    )
    row = recipients.iloc[0]
    assert row["resolved_entity_id"] == ""
    assert row["resolved_entity_type"] == "unresolved"
    assert row["match_method"] == "normalized_name_discovery_only"
    assert row["identity_status"] == "CANDIDATE_NOT_IDENTITY"
    assert int(row["candidate_count"]) == 1
    assert "H1" in json.loads(row["candidate_entity_ids"])


def test_edges_never_verify_name_only_endpoint(tmp_path) -> None:
    _write_fixture(tmp_path)
    builder.run(root=tmp_path)

    edges = pd.read_csv(
        tmp_path / "data" / "staging" / "processed" / "pr_campaign_finance_edges.csv",
        dtype=str,
        keep_default_na=False,
    )
    schedule_a = edges[edges["source_dataset"] == "fec_schedule_a"].iloc[0]
    assert schedule_a["identity_status"] == "CANDIDATE_NOT_IDENTITY"
    assert schedule_a["source_identity_basis"] == "transaction_record_only"
    assert schedule_a["source_entity_type"] == "unresolved_donor_record"

    schedule_e = edges[edges["source_dataset"] == "fec_schedule_e"]
    candidate_only = schedule_e[schedule_e["target_identity_basis"] == "normalized_name_discovery_only"]
    verified = schedule_e[schedule_e["target_identity_basis"] == "fec_candidate_id"]
    assert len(candidate_only) == 1
    assert candidate_only.iloc[0]["identity_status"] == "CANDIDATE_NOT_IDENTITY"
    assert candidate_only.iloc[0]["target_entity_type"] == "unresolved_candidate_record"
    assert len(verified) == 1
    assert verified.iloc[0]["identity_status"] == "VERIFIED_ID"
    assert verified.iloc[0]["source_identity_basis"] == "fec_committee_id"


def test_identity_safety_detects_legacy_name_only_promotion(tmp_path) -> None:
    _write_fixture(tmp_path)
    builder.run(root=tmp_path)
    processed = tmp_path / "data" / "staging" / "processed"

    recipients = pd.read_csv(
        processed / "pr_campaign_finance_recipient_resolution.csv",
        dtype=str,
        keep_default_na=False,
    )
    recipients.loc[0, "resolved_entity_id"] = "H1"
    recipients.loc[0, "resolved_entity_type"] = "candidate"
    recipients.loc[0, "match_method"] = "exact_normalized_name"
    recipients.loc[0, "identity_status"] = "VERIFIED_ID"
    recipients.to_csv(processed / "pr_campaign_finance_recipient_resolution.csv", index=False)

    safety = validator.identity_safety(tmp_path)
    assert safety["ok"] is False
    assert any("name_only_identity_promotion" in item for item in safety["blockers"])


def test_identity_safety_accepts_hardened_outputs(tmp_path) -> None:
    _write_fixture(tmp_path)
    builder.run(root=tmp_path)
    safety = validator.identity_safety(tmp_path)

    assert safety["ok"] is True
    assert safety["blockers"] == []
    assert safety["metrics"]["recipient_name_only_promotions"] == 0
