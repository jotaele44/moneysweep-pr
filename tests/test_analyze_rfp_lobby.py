"""Tests for analyze_rfp_lobby — vendor matching and influence score formula."""

import math

import pandas as pd
import pytest

from scripts.analyze_rfp_lobby import (
    _match_vendor_to_lda,
    _parse_dates,
    MIN_SCORE,
    WINDOW_DAYS,
)


def test_parse_dates_valid():
    df = pd.DataFrame({"posted_date": ["2023-01-15", "2022-06-30"]})
    result = _parse_dates(df, "posted_date")
    assert result.iloc[0].year == 2023
    assert result.iloc[1].month == 6


def test_parse_dates_invalid_coerced():
    df = pd.DataFrame({"posted_date": ["not-a-date", "2023-03-01"]})
    result = _parse_dates(df, "posted_date")
    assert pd.isna(result.iloc[0])
    assert result.iloc[1].year == 2023


# ---------------------------------------------------------------------------
# _match_vendor_to_lda
# ---------------------------------------------------------------------------

def _make_lda(names):
    return pd.DataFrame({"client_name_normalized": names})


def test_match_vendor_empty_lda():
    result = _match_vendor_to_lda("ACME CORP", pd.DataFrame())
    assert result.empty


def test_match_vendor_empty_name():
    result = _match_vendor_to_lda("", _make_lda(["ACME CORP"]))
    assert result.empty


def test_match_vendor_exact_hit():
    lda = _make_lda(["ACME CORP", "OTHER FIRM"])
    result = _match_vendor_to_lda("ACME CORP", lda)
    assert len(result) == 1
    assert result.iloc[0]["client_name_normalized"] == "ACME CORP"


def test_match_vendor_no_hit_below_threshold():
    lda = _make_lda(["TOTALLY DIFFERENT COMPANY"])
    result = _match_vendor_to_lda("ACME CORP", lda)
    assert result.empty


def test_match_vendor_missing_column():
    # If client_name_normalized column absent, returns empty
    lda = pd.DataFrame({"other_col": ["ACME CORP"]})
    result = _match_vendor_to_lda("ACME CORP", lda)
    assert result.empty


# ---------------------------------------------------------------------------
# Influence score formula
# ---------------------------------------------------------------------------

def _influence_score(lda_flag, lobby_lead_days, lda_spend, window_days=WINDOW_DAYS):
    """Replicate the influence score formula from analyze_rfp_lobby.run()."""
    if lda_flag and lobby_lead_days is not None:
        recency = max(1, window_days - lobby_lead_days) / window_days
        spend_weight = math.log1p(lda_spend) / math.log1p(1_000_000)
        return round(min(1.0, recency * (0.6 + 0.4 * spend_weight)), 4)
    return 0.0


def test_influence_score_no_flag():
    assert _influence_score(0, None, 0) == 0.0


def test_influence_score_flag_recent_high_spend():
    # lead_days=0 → recency = max(1,180)/180 = 1.0; spend at $1M → spend_weight = 1.0
    score = _influence_score(1, 0, 1_000_000)
    assert score == pytest.approx(1.0)


def test_influence_score_flag_old_no_spend():
    # lobby_lead_days close to window → recency ≈ 1/180
    score = _influence_score(1, WINDOW_DAYS - 1, 0)
    expected_recency = 1 / WINDOW_DAYS
    expected = round(expected_recency * 0.6, 4)
    assert score == pytest.approx(expected, abs=1e-4)


def test_influence_score_capped_at_one():
    score = _influence_score(1, 0, 999_999_999_999)
    assert score <= 1.0


def test_influence_score_increases_with_spend():
    low  = _influence_score(1, 30, 0)
    high = _influence_score(1, 30, 500_000)
    assert high > low


def test_influence_score_increases_with_recency():
    recent = _influence_score(1, 5,   0)   # lobbied 5 days before RFP
    old    = _influence_score(1, 170, 0)   # lobbied 170 days before RFP
    assert recent > old


# ---------------------------------------------------------------------------
# Constants sanity
# ---------------------------------------------------------------------------

def test_window_days_positive():
    assert WINDOW_DAYS > 0


def test_min_score_in_range():
    assert 0.0 < MIN_SCORE < 1.0
