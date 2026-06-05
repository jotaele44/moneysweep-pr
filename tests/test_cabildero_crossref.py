"""Tests for the cabildero / registrant crossref in analyze_political_crossref."""
from pathlib import Path

import pandas as pd
import pytest

from scripts import analyze_political_crossref as mod


def _processed(tmp_path: Path) -> Path:
    p = tmp_path / "data" / "staging" / "processed"
    p.mkdir(parents=True, exist_ok=True)
    return p


@pytest.mark.unit
def test_missing_sources_returns_status(tmp_path):
    result = mod.build_cabildero_crossref(root=tmp_path)
    assert result["status"] == "MISSING_LOBBYING_SOURCES"


@pytest.mark.unit
def test_registrant_dual_influence_and_source_union(tmp_path):
    proc = _processed(tmp_path)
    # A registrant that lobbies federally AND receives a federal award (dual-influence),
    # plus the same firm in the PR OEG cabildero registry → source "both".
    pd.DataFrame([
        {"registrant_name": "Acme Strategies LLC", "client_name": "Genera PR",
         "filing_uuid": "F1", "income": "50000", "filing_year": "2022",
         "general_issue_codes": "ENERGY"},
        {"registrant_name": "Acme Strategies LLC", "client_name": "LUMA",
         "filing_uuid": "F2", "income": "30000", "filing_year": "2023",
         "general_issue_codes": "ENERGY"},
    ]).to_csv(proc / "pr_lda_filings.csv", index=False)

    pd.DataFrame([
        {"lobbyist_name": "Acme Strategies", "client_name": "Cliente Local",
         "registration_year": "2021"},
        {"lobbyist_name": "Solo PR Lobbyist", "client_name": "Otro Cliente",
         "registration_year": "2020"},
    ]).to_csv(proc / "pr_cabilderos.csv", index=False)

    pd.DataFrame([
        {"recipient_name": "Acme Strategies LLC", "obligated_amount": "1000000",
         "award_id": "AW1", "source_dataset": "usaspending", "fiscal_year": "2022"},
    ]).to_csv(proc / "pr_all_awards_master.csv", index=False)

    result = mod.build_cabildero_crossref(root=tmp_path)
    assert result["status"] == "OK"
    out = pd.read_csv(proc / "pr_cabildero_crossref.csv")

    acme = out[out["normalized_name"] == "ACME STRATEGIES"].iloc[0]
    assert acme["source"] == "both"
    assert acme["lda_filing_count"] == 2
    assert acme["anchor_status"] == "matched_to_contract"
    assert float(acme["total_awards_obligated"]) == 1_000_000
    assert "Genera PR" in acme["lda_clients_represented"]

    solo = out[out["normalized_name"] == "SOLO PR LOBBYIST"].iloc[0]
    assert solo["source"] == "pr_oeg"
    assert solo["anchor_status"] == "unmatched_no_anchor"


@pytest.mark.unit
def test_lda_only_registrant_tagged_federal(tmp_path):
    proc = _processed(tmp_path)
    pd.DataFrame([
        {"registrant_name": "Federal Only Firm", "client_name": "X",
         "filing_uuid": "F9", "income": "1000", "filing_year": "2024"},
    ]).to_csv(proc / "pr_lda_filings.csv", index=False)
    result = mod.build_cabildero_crossref(root=tmp_path)
    assert result["status"] == "OK"
    out = pd.read_csv(proc / "pr_cabildero_crossref.csv")
    assert out.iloc[0]["source"] == "federal_lda"
