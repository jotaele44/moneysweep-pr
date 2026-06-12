"""Tests for the NGO ↔ political-donation crossref in analyze_political_crossref."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from scripts import analyze_political_crossref as mod


def _processed(tmp_path: Path) -> Path:
    p = tmp_path / "data" / "staging" / "processed"
    p.mkdir(parents=True, exist_ok=True)
    (p / "ngos").mkdir(parents=True, exist_ok=True)
    return p


def _write_ngos(processed: Path, rows: list[dict]) -> Path:
    path = processed / "ngos" / "ngos_master.csv"
    pd.DataFrame(rows).to_csv(path, index=False)
    return path


@pytest.mark.unit
def test_missing_ngo_master_returns_status(tmp_path):
    result = mod.build_ngo_donation_crossref(root=tmp_path)
    assert result["status"] == "MISSING_NGO_MASTER"


@pytest.mark.unit
def test_missing_all_donation_feeds_returns_status(tmp_path):
    proc = _processed(tmp_path)
    _write_ngos(
        proc,
        [
            {
                "ngo_id": "ngo_x",
                "legal_name": "Some NGO",
                "ein": "660000000",
                "irs_subsection": "4",
            }
        ],
    )
    result = mod.build_ngo_donation_crossref(root=tmp_path)
    assert result["status"] == "MISSING_DONATIONS"


@pytest.mark.unit
def test_match_against_fec_and_cee_classifies_subsection(tmp_path):
    proc = _processed(tmp_path)
    _write_ngos(
        proc,
        [
            # 501(c)(4) — likely_political — matches both FEC and CEE
            {
                "ngo_id": "ngo_4",
                "legal_name": "Action Fund Inc",
                "ein": "660000001",
                "aliases": "",
                "municipality": "San Juan",
                "irs_subsection": "4",
                "entity_type": "civic",
                "confidence": "90",
                "review_status": "confirmed",
            },
            # 501(c)(3) — restricted_charity — matches FEC only
            {
                "ngo_id": "ngo_3",
                "legal_name": "Charity Foundation",
                "ein": "660000002",
                "aliases": "",
                "municipality": "Ponce",
                "irs_subsection": "3",
                "entity_type": "charity",
                "confidence": "85",
                "review_status": "confirmed",
            },
            # No matches anywhere — must NOT appear in output
            {
                "ngo_id": "ngo_none",
                "legal_name": "Unconnected NGO",
                "ein": "660000003",
                "aliases": "",
                "municipality": "Mayaguez",
                "irs_subsection": "3",
                "entity_type": "charity",
                "confidence": "80",
                "review_status": "confirmed",
            },
        ],
    )

    pd.DataFrame(
        [
            {
                "contributor_name": "Action Fund Inc",
                "contribution_receipt_amount": "5000",
                "contribution_receipt_date": "2022-03-01",
                "committee_name": "Friends of X PAC",
                "candidate_name": "Candidate A",
                "is_individual": "False",
            },
            {
                "contributor_name": "Action Fund Inc",
                "contribution_receipt_amount": "2500",
                "contribution_receipt_date": "2023-04-01",
                "committee_name": "Friends of X PAC",
                "candidate_name": "Candidate B",
                "is_individual": "False",
            },
            {
                "contributor_name": "Charity Foundation",
                "contribution_receipt_amount": "1000",
                "contribution_receipt_date": "2021-09-15",
                "committee_name": "Some Committee",
                "candidate_name": "",
                "is_individual": "False",
            },
        ]
    ).to_csv(proc / "pr_fec_contributions.csv", index=False)

    pd.DataFrame(
        [
            {
                "donor_name": "Action Fund Inc",
                "amount": "750",
                "contribution_date": "2024-05-01",
                "candidate_or_committee": "Comite Local",
                "party": "PPD",
            },
            {
                "donor_name": "Action Fund Inc",
                "amount": "250",
                "contribution_date": "2024-06-01",
                "candidate_or_committee": "Comite Local",
                "party": "PPD",
            },
        ]
    ).to_csv(proc / "pr_donaciones.csv", index=False)

    result = mod.build_ngo_donation_crossref(root=tmp_path)
    assert result["status"] == "OK"
    assert result["rows"] == 2

    out = pd.read_csv(proc / "ngos" / "ngo_political_donations.csv")
    by_id = {row["ngo_id"]: row for _, row in out.iterrows()}

    assert "ngo_none" not in by_id, "unmatched NGO must not surface in the crossref"

    c4 = by_id["ngo_4"]
    assert c4["donation_sources"] == "both"
    assert c4["politically_active_subsection"] == "likely_political"
    assert float(c4["fec_total_contributions"]) == 7500
    assert int(c4["fec_contribution_count"]) == 2
    assert float(c4["pr_total_contributions"]) == 1000
    assert int(c4["pr_contribution_count"]) == 2
    assert float(c4["total_political_contributions"]) == 8500
    assert "Friends of X PAC" in c4["fec_committees_funded"]
    assert "PPD" in c4["pr_parties"]

    c3 = by_id["ngo_3"]
    assert c3["donation_sources"] == "federal_fec"
    assert c3["politically_active_subsection"] == "restricted_charity"
    assert float(c3["fec_total_contributions"]) == 1000


@pytest.mark.unit
def test_alias_only_match(tmp_path):
    proc = _processed(tmp_path)
    aliases = json.dumps(["Friends of the Coast Action Fund", "FCAF"])
    _write_ngos(
        proc,
        [
            {
                "ngo_id": "ngo_alias",
                "legal_name": "Coastal Action Foundation",  # no FEC hit
                "ein": "660000010",
                "aliases": aliases,  # FCAF is the donor name in FEC
                "municipality": "Aguadilla",
                "irs_subsection": "4",
                "entity_type": "civic",
                "confidence": "75",
                "review_status": "strong_probable",
            }
        ],
    )
    pd.DataFrame(
        [
            {
                "contributor_name": "FCAF",
                "contribution_receipt_amount": "9999",
                "contribution_receipt_date": "2022-01-01",
                "committee_name": "Coastal PAC",
                "candidate_name": "",
                "is_individual": "False",
            }
        ]
    ).to_csv(proc / "pr_fec_contributions.csv", index=False)

    result = mod.build_ngo_donation_crossref(root=tmp_path)
    assert result["status"] == "OK"
    out = pd.read_csv(proc / "ngos" / "ngo_political_donations.csv")
    assert len(out) == 1
    row = out.iloc[0]
    assert row["ngo_id"] == "ngo_alias"
    assert row["matched_alias"] == "FCAF"
    assert float(row["fec_total_contributions"]) == 9999


@pytest.mark.unit
def test_fec_individuals_are_excluded(tmp_path):
    """An IND-type FEC row that happens to share a name must NOT match."""
    proc = _processed(tmp_path)
    _write_ngos(
        proc,
        [
            {
                "ngo_id": "ngo_collision",
                "legal_name": "John Q Public",
                "ein": "660000020",
                "aliases": "",
                "municipality": "San Juan",
                "irs_subsection": "4",
                "entity_type": "civic",
                "confidence": "60",
                "review_status": "needs_review",
            }
        ],
    )
    pd.DataFrame(
        [
            {
                "contributor_name": "John Q Public",
                "contribution_receipt_amount": "500",
                "contribution_receipt_date": "2022-01-01",
                "committee_name": "Some PAC",
                "candidate_name": "Candidate Z",
                "is_individual": "True",
                "entity_type": "IND",
            }
        ]
    ).to_csv(proc / "pr_fec_contributions.csv", index=False)
    result = mod.build_ngo_donation_crossref(root=tmp_path)
    # No org-level matches — must surface as EMPTY with header-only CSV.
    assert result["rows"] == 0
    assert result["status"] in {"EMPTY", "MISSING_DONATIONS"}


@pytest.mark.unit
def test_oce_donation_feed_is_picked_up(tmp_path):
    """pr_oce_donations.csv must also feed the PR side of the crossref."""
    proc = _processed(tmp_path)
    _write_ngos(
        proc,
        [
            {
                "ngo_id": "ngo_oce",
                "legal_name": "Civic Trust",
                "ein": "660000030",
                "aliases": "",
                "municipality": "Bayamon",
                "irs_subsection": "6",
                "entity_type": "civic",
                "confidence": "70",
                "review_status": "probable",
            }
        ],
    )
    pd.DataFrame(
        [
            {
                "donor_name": "Civic Trust",
                "amount": "2000",
                "contribution_date": "2024-09-01",
                "candidate_or_committee": "Comite OCE",
                "party": "PNP",
            }
        ]
    ).to_csv(proc / "pr_oce_donations.csv", index=False)
    result = mod.build_ngo_donation_crossref(root=tmp_path)
    assert result["status"] == "OK"
    out = pd.read_csv(proc / "ngos" / "ngo_political_donations.csv")
    row = out.iloc[0]
    assert row["donation_sources"] == "pr"
    assert float(row["pr_total_contributions"]) == 2000
    assert row["politically_active_subsection"] == "likely_political"
