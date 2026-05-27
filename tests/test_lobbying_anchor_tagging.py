"""Tests for the lobbying anchor-tagging logic in analyze_political_crossref."""
from __future__ import annotations

import csv
from pathlib import Path

import pandas as pd
import pytest

from scripts.analyze_political_crossref import (
    _classify_anchor,
    _load_anchor_sets,
    _normalize,
    build_lobbying_crossref,
)


# ---------------------------------------------------------------------------
# Fixture: minimal processed-dir layout exercising all four anchor statuses.
# ---------------------------------------------------------------------------

AWARDS_ROWS = [
    {
        "award_id": "A1",
        "awarding_agency": "Federal Agency",
        "recipient_name": "Acme Federal Corp",
        "obligated_amount": "100000",
        "source_dataset": "pr_all_awards_master.csv",
        "fiscal_year": "2024",
    }
]

SUBAWARDS_ROWS = [
    {
        "sub_award_id": "S1",
        "sub_recipient_name": "Beta Subcontractor LLC",
        "sub_obligated_amount": "50000",
    }
]

EMMA_ROWS = [
    {
        "issuer_name": "PR Highway Authority",
        "underwriter_name": "Gamma Underwriters Inc",
        "par_amount": "500000",
        "cusip": "1234ABC",
    }
]

LDA_ROWS = [
    # Matches a federal contract recipient.
    {
        "client_name": "Acme Federal Corp",
        "client_state": "PR",
        "client_description": "Engineering services",
        "filing_uuid": "F-CONTRACT",
        "filing_year": "2024",
        "income": "20000",
        "expenses": "0",
        "general_issue_codes": "TRA",
        "lobbyist_names": "Lobbyist A",
        "registrant_name": "Reg A",
    },
    # Matches a subaward recipient only.
    {
        "client_name": "Beta Subcontractor LLC",
        "client_state": "PR",
        "client_description": "Construction sub",
        "filing_uuid": "F-SUB",
        "filing_year": "2024",
        "income": "15000",
        "expenses": "0",
        "general_issue_codes": "TRA",
        "lobbyist_names": "Lobbyist B",
        "registrant_name": "Reg B",
    },
    # Matches an EMMA underwriter only.
    {
        "client_name": "Gamma Underwriters Inc",
        "client_state": "PR",
        "client_description": "Bond services",
        "filing_uuid": "F-EMMA",
        "filing_year": "2024",
        "income": "30000",
        "expenses": "0",
        "general_issue_codes": "FIN",
        "lobbyist_names": "Lobbyist C",
        "registrant_name": "Reg C",
    },
    # No anchor anywhere — must surface as unmatched_no_anchor (Arcadis-style).
    {
        "client_name": "Arcadis Caribe",
        "client_state": "PR",
        "client_description": "Engineering consultancy",
        "filing_uuid": "F-ORPHAN",
        "filing_year": "2024",
        "income": "75000",
        "expenses": "0",
        "general_issue_codes": "ENV",
        "lobbyist_names": "Lobbyist D",
        "registrant_name": "Reg D",
    },
]


def _write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


@pytest.fixture
def lobbying_repo(tmp_path: Path) -> Path:
    processed = tmp_path / "data" / "staging" / "processed"
    _write_csv(processed / "pr_all_awards_master.csv", AWARDS_ROWS)
    _write_csv(processed / "pr_subawards_master.csv", SUBAWARDS_ROWS)
    _write_csv(processed / "pr_emma_bonds.csv", EMMA_ROWS)
    _write_csv(processed / "pr_lda_filings.csv", LDA_ROWS)
    return tmp_path


# ---------------------------------------------------------------------------
# Unit tests for the helpers
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_load_anchor_sets_collects_three_buckets(lobbying_repo: Path) -> None:
    anchors = _load_anchor_sets(lobbying_repo / "data" / "staging" / "processed")
    assert _normalize("Acme Federal Corp") in anchors["contract"]
    assert _normalize("Beta Subcontractor LLC") in anchors["subaward"]
    assert _normalize("Gamma Underwriters Inc") in anchors["emma_underwriter"]


@pytest.mark.unit
def test_classify_anchor_priority_contract_over_subaward() -> None:
    anchors = {
        "contract": {"FOO"},
        "subaward": {"FOO"},
        "emma_underwriter": {"FOO"},
    }
    status, src = _classify_anchor("FOO", anchors)
    assert status == "matched_to_contract"
    assert "pr_all_awards_master.csv" in src


@pytest.mark.unit
def test_classify_anchor_subaward_when_no_contract() -> None:
    anchors = {"contract": set(), "subaward": {"BAR"}, "emma_underwriter": set()}
    status, src = _classify_anchor("BAR", anchors)
    assert status == "matched_to_subaward"
    assert src == "pr_subawards_master.csv"


@pytest.mark.unit
def test_classify_anchor_emma_when_only_emma() -> None:
    anchors = {"contract": set(), "subaward": set(), "emma_underwriter": {"BAZ"}}
    status, src = _classify_anchor("BAZ", anchors)
    assert status == "matched_to_emma_underwriter"
    assert "pr_emma_bonds.csv" in src


@pytest.mark.unit
def test_classify_anchor_unmatched_when_absent() -> None:
    anchors = {"contract": set(), "subaward": set(), "emma_underwriter": set()}
    status, src = _classify_anchor("QUUX", anchors)
    assert status == "unmatched_no_anchor"
    assert src == ""


# ---------------------------------------------------------------------------
# Integration: full build_lobbying_crossref over the synthetic repo.
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_build_lobbying_crossref_emits_all_four_anchor_statuses(
    lobbying_repo: Path,
) -> None:
    result = build_lobbying_crossref(lobbying_repo)
    assert result["status"] == "OK"
    out_path = Path(result["path"])
    assert out_path.exists()

    df = pd.read_csv(out_path, dtype=str)
    # All four LDA clients surface (left-merge preserves unanchored rows).
    assert len(df) == 4

    expected_columns = {
        "normalized_name",
        "lda_client_name",
        "anchor_status",
        "anchor_source_dataset",
        "anchor_evidence_id",
    }
    assert expected_columns.issubset(set(df.columns))

    by_client = {row["lda_client_name"]: row for _, row in df.iterrows()}

    assert by_client["Acme Federal Corp"]["anchor_status"] == "matched_to_contract"
    assert by_client["Beta Subcontractor LLC"]["anchor_status"] == "matched_to_subaward"
    assert by_client["Gamma Underwriters Inc"]["anchor_status"] == "matched_to_emma_underwriter"

    orphan = by_client["Arcadis Caribe"]
    assert orphan["anchor_status"] == "unmatched_no_anchor"
    # Empty source dataset round-trips through CSV as NaN.
    assert pd.isna(orphan["anchor_source_dataset"]) or orphan["anchor_source_dataset"] == ""
    # Evidence carries the filing_uuid so the unmatched row stays traceable.
    assert orphan["anchor_evidence_id"] == "F-ORPHAN"

    # Anchor breakdown summary mirrors the per-row tags.
    breakdown = result["anchor_breakdown"]
    assert breakdown["matched_to_contract"] == 1
    assert breakdown["matched_to_subaward"] == 1
    assert breakdown["matched_to_emma_underwriter"] == 1
    assert breakdown["unmatched_no_anchor"] == 1


@pytest.mark.integration
def test_build_lobbying_crossref_missing_awards_returns_status(tmp_path: Path) -> None:
    # No processed dir at all → MISSING_AWARDS.
    result = build_lobbying_crossref(tmp_path)
    assert result["status"] == "MISSING_AWARDS"
    assert result["rows"] == 0
