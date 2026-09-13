import pandas as pd
import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from server.backend import campaign_finance as api
from server.backend.main import app


@pytest.mark.unit
def test_summary_and_contributions_are_graceful_without_files(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "PROCESSED", tmp_path)
    api._CACHE.clear()
    summary = api.campaign_finance_summary()
    assert summary["totalContributionRows"] == 0
    assert summary["hasData"] is False
    assert summary["materializedFileCount"] == 0
    assert summary["emptyState"]
    page = api.campaign_finance_contributions(source="all", limit=100, offset=0)
    assert page == {"rows": [], "total": 0, "limit": 100, "offset": 0}


@pytest.mark.unit
def test_contribution_endpoint_unifies_fec_and_oce(tmp_path, monkeypatch):
    pd.DataFrame(
        [
            {
                "contributor_name": "DONOR A",
                "contribution_receipt_amount": "100",
                "contribution_receipt_date": "2024-01-01",
                "committee_name": "PAC A",
                "cycle": "2024",
                "is_individual": "True",
                "committee_id": "C1",
                "candidate_id": "",
            }
        ]
    ).to_csv(tmp_path / "pr_fec_contributions.csv", index=False)
    pd.DataFrame(
        [
            {
                "donor_name": "DONOR B",
                "amount": "200",
                "contribution_date": "2024-02-01",
                "candidate_or_committee": "COMITE B",
                "party": "PIP",
                "cycle": "2024",
            }
        ]
    ).to_csv(tmp_path / "pr_oce_donations.csv", index=False)
    monkeypatch.setattr(api, "PROCESSED", tmp_path)
    api._CACHE.clear()
    page = api.campaign_finance_contributions(source="all", limit=100, offset=0)
    assert page["total"] == 2
    assert {row["source"] for row in page["rows"]} == {"fec", "oce"}
    assert sum(row["amount"] for row in page["rows"]) == 300


@pytest.mark.unit
def test_http_contracts_match_dashboard_shapes(tmp_path, monkeypatch):
    from starlette.testclient import TestClient

    pd.DataFrame(
        [
            {
                "donor_name": "DONOR REAL",
                "amount": "250.50",
                "contribution_date": "2024-03-02",
                "candidate_or_committee": "COMMITTEE REAL",
                "party": "PIP",
                "cycle": "2024",
            }
        ]
    ).to_csv(tmp_path / "pr_oce_donations.csv", index=False)
    pd.DataFrame(
        [
            {
                "candidate_entity_id": "candidate-1",
                "canonical_name": "CANDIDATE REAL",
                "party": "PIP",
                "office_sought": "Governor",
                "confidence": "82",
                "review_status": "reviewed",
            }
        ]
    ).to_csv(tmp_path / "pr_campaign_finance_candidates.csv", index=False)
    pd.DataFrame(
        [
            {
                "committee_name": "COMMITTEE REAL",
                "report_number": "R-1",
                "report_type": "Quarterly",
                "reporting_period": "2024 Q1",
                "filed_at": "2024-04-01",
            }
        ]
    ).to_csv(tmp_path / "pr_oce_reports.csv", index=False)

    monkeypatch.setattr(api, "PROCESSED", tmp_path)
    api._CACHE.clear()
    with TestClient(app) as client:
        summary = client.get("/campaign-finance/summary")
        contributions = client.get(
            "/campaign-finance/contributions",
            params={"source": "oce", "q": "donor real", "limit": 10},
        )
        entities = client.get("/campaign-finance/entities", params={"q": "candidate real"})
        reports = client.get("/campaign-finance/reports", params={"q": "committee real"})

    assert summary.status_code == 200
    summary_body = summary.json()
    assert summary_body["hasData"] is True
    assert summary_body["totalContributionRows"] == 1
    assert summary_body["totalContributionAmount"] == 250.5
    assert summary_body["sources"][2]["status"] == "available"
    assert summary_body["sources"][2]["file"] == "pr_oce_donations.csv"

    assert contributions.status_code == 200
    contribution_body = contributions.json()
    assert contribution_body == {
        "rows": [
            {
                "source": "oce",
                "donorName": "DONOR REAL",
                "amount": 250.5,
                "date": "2024-03-02",
                "recipientName": "COMMITTEE REAL",
                "party": "PIP",
                "cycle": "2024",
                "donorType": "unknown",
                "committeeId": "",
                "candidateId": "",
            }
        ],
        "total": 1,
        "limit": 10,
        "offset": 0,
    }
    assert entities.status_code == 200
    assert entities.json()[0]["entityId"] == "candidate-1"
    assert reports.status_code == 200
    assert reports.json()[0]["report_number"] == "R-1"


@pytest.mark.unit
def test_empty_or_partial_csvs_do_not_break_routes(tmp_path, monkeypatch):
    (tmp_path / "pr_fec_contributions.csv").write_text("", encoding="utf-8")
    pd.DataFrame([{"unexpected": "value"}]).to_csv(tmp_path / "pr_oce_reports.csv", index=False)
    monkeypatch.setattr(api, "PROCESSED", tmp_path)
    api._CACHE.clear()

    assert api.campaign_finance_contributions(source="fec", limit=10, offset=0)["rows"] == []
    assert api.campaign_finance_reports(q="missing", limit=10) == []
