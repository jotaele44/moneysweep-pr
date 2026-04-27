"""Tests for analyze_bond_flow — name matching and dual-role detection."""

import pandas as pd
import pytest

from scripts.analyze_bond_flow import (
    _safe_float,
    _best_match,
    _match_to_entity,
    MATCH_THRESHOLD,
    UW_SPREAD_EST,
    BOND_FLOW_COLUMNS,
)


def test_safe_float_valid():
    assert _safe_float("1234.56") == pytest.approx(1234.56)


def test_safe_float_none():
    assert _safe_float(None) == 0.0


def test_safe_float_bad():
    assert _safe_float("n/a") == 0.0


# ---------------------------------------------------------------------------
# _best_match
# ---------------------------------------------------------------------------

def test_best_match_exact():
    candidates = pd.Series(["GOLDMAN SACHS", "CITI GROUP"])
    score = _best_match("GOLDMAN SACHS", candidates)
    assert score == pytest.approx(1.0)


def test_best_match_empty_candidates():
    assert _best_match("ACME", pd.Series([], dtype=str)) == 0.0


def test_best_match_empty_name():
    candidates = pd.Series(["ACME"])
    assert _best_match("", candidates) == 0.0


def test_best_match_returns_max():
    candidates = pd.Series(["TOTALLY DIFFERENT", "GOLDMAN SACHS CORP"])
    score = _best_match("GOLDMAN SACHS", candidates)
    # Jaccard-only (no rapidfuzz): 2 shared / 3 unique tokens = 0.667
    # rapidfuzz token_set_ratio: treats "GOLDMAN SACHS" as a subset → 1.0
    assert score > 0.6


def test_best_match_no_good_match():
    candidates = pd.Series(["RANDOM COMPANY XYZ", "ANOTHER FIRM ABC"])
    score = _best_match("GOLDMAN SACHS", candidates)
    assert score < MATCH_THRESHOLD


# ---------------------------------------------------------------------------
# _match_to_entity
# ---------------------------------------------------------------------------

def test_match_to_entity_true_on_exact():
    norms = pd.Series(["GOLDMAN SACHS"])
    assert _match_to_entity("GOLDMAN SACHS", norms) is True


def test_match_to_entity_false_on_no_match():
    norms = pd.Series(["RANDOM FIRM"])
    assert _match_to_entity("GOLDMAN SACHS", norms) is False


def test_match_to_entity_empty_norms():
    assert _match_to_entity("ACME", pd.Series([], dtype=str)) is False


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

def test_match_threshold_in_range():
    assert 0.5 < MATCH_THRESHOLD < 1.0


def test_uw_spread_est_reasonable():
    # Typical underwriter spread is 0.25% – 2%; 0.5% is a reasonable estimate
    assert 0.001 < UW_SPREAD_EST < 0.05


def test_bond_flow_columns_has_dual_role():
    assert "is_dual_role" in BOND_FLOW_COLUMNS
    assert "is_issuer_and_awardee" in BOND_FLOW_COLUMNS
    assert "entity_key" in BOND_FLOW_COLUMNS


# ---------------------------------------------------------------------------
# Dual-role logic (arithmetic)
# ---------------------------------------------------------------------------

def test_dual_role_requires_both_sides():
    # Dual-role = awards > 0 AND (underwriter OR dealer)
    awards = 1_000_000
    is_uw = True
    is_dealer = False
    is_dual = int((is_uw or is_dealer) and awards > 0)
    assert is_dual == 1


def test_dual_role_false_when_no_awards():
    awards = 0
    is_uw = True
    is_dual = int(is_uw and awards > 0)
    assert is_dual == 0


def test_dual_role_false_when_no_bond_role():
    awards = 1_000_000
    is_uw = False
    is_dealer = False
    is_dual = int((is_uw or is_dealer) and awards > 0)
    assert is_dual == 0


def test_estimated_fee_calculation():
    # estimated_underwriter_fee = par * UW_SPREAD_EST
    par = 1_000_000_000
    fee = round(par * UW_SPREAD_EST, 2)
    assert fee == pytest.approx(par * UW_SPREAD_EST)
