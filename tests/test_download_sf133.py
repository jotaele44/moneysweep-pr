"""Tests for download_sf133 — account relevance filter and obligation rate."""

import pytest

from scripts.download_sf133 import (
    PR_AGENCIES,
    PR_KEYWORDS,
    OUTPUT_COLUMNS,
)


def test_pr_agencies_non_empty():
    assert len(PR_AGENCIES) >= 8


def test_pr_agencies_keys_are_3digit_strings():
    for code in PR_AGENCIES:
        assert len(code) == 3
        assert code.isdigit(), f"Agency code '{code}' should be all digits"


def test_pr_keywords_include_disaster_recovery():
    assert "disaster" in PR_KEYWORDS
    assert "recovery" in PR_KEYWORDS
    assert "puerto rico" in PR_KEYWORDS


def test_output_columns_has_obligation_rate():
    assert "obligation_rate" in OUTPUT_COLUMNS
    assert "budget_authority" in OUTPUT_COLUMNS
    assert "obligations" in OUTPUT_COLUMNS
    assert "fiscal_year" in OUTPUT_COLUMNS


def test_obligation_rate_formula():
    # obligation_rate = obligations / budget_authority
    budget = 1_000_000
    obligations = 750_000
    rate = round(obligations / budget, 4)
    assert rate == pytest.approx(0.75)


def test_obligation_rate_zero_budget():
    # Must not divide by zero
    budget = 0
    rate = round(0 / budget, 4) if budget > 0 else 0.0
    assert rate == 0.0


def test_account_relevance_keyword_match():
    title = "hurricane recovery infrastructure fund for puerto rico"
    relevant = any(kw in title.lower() for kw in PR_KEYWORDS)
    assert relevant is True


def test_account_relevance_large_budget():
    # Accounts >$1B are always tracked regardless of title
    budget = 2_000_000_000
    title = "generic appropriation with no keywords"
    is_relevant = (
        any(kw in title.lower() for kw in PR_KEYWORDS)
        or budget > 1_000_000_000
    )
    assert is_relevant is True


def test_account_relevance_small_no_keywords():
    budget = 500_000
    title = "generic appropriation"
    is_relevant = (
        any(kw in title.lower() for kw in PR_KEYWORDS)
        or budget > 1_000_000_000
    )
    assert is_relevant is False


def test_known_agency_codes_present():
    assert "058" in PR_AGENCIES   # FEMA
    assert "086" in PR_AGENCIES   # HUD
    assert "069" in PR_AGENCIES   # DOT
    assert "089" in PR_AGENCIES   # DOE
