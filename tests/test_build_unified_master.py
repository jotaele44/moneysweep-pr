"""Tests for scripts/build_unified_master.py — name normalization, FY derivation, pop_state."""

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.build_unified_master import (
    _derive_fiscal_year,
    _normalize_name,
    _standardize_pop_state,
)


# ---------------------------------------------------------------------------
# _normalize_name
# ---------------------------------------------------------------------------

class TestNormalizeName:
    def test_empty_string(self):
        assert _normalize_name("") == ""

    def test_nan(self):
        assert _normalize_name(float("nan")) == ""

    def test_none(self):
        assert _normalize_name(None) == ""

    def test_uppercase(self):
        assert _normalize_name("crowley") == "CROWLEY"

    def test_strips_trailing_inc(self):
        assert _normalize_name("Microsoft Inc") == "MICROSOFT"

    def test_strips_trailing_corp(self):
        # Note: only "CORP" is in the suffix set, not "CORPORATION"
        assert _normalize_name("Acme Corp") == "ACME"

    def test_strips_punctuation(self):
        assert _normalize_name("Triple-S Mgmt, Inc.") == "TRIPLE S MGMT"

    def test_strips_multiple_trailing_suffixes(self):
        assert _normalize_name("Foo Inc Corp") == "FOO"


# ---------------------------------------------------------------------------
# _derive_fiscal_year
# ---------------------------------------------------------------------------

class TestDeriveFiscalYear:
    def test_january_is_same_fy(self):
        s = pd.Series(["2024-01-15"])
        assert _derive_fiscal_year(s).iloc[0] == "2024"

    def test_september_is_same_fy(self):
        s = pd.Series(["2024-09-30"])
        assert _derive_fiscal_year(s).iloc[0] == "2024"

    def test_october_rolls_forward(self):
        s = pd.Series(["2024-10-01"])
        assert _derive_fiscal_year(s).iloc[0] == "2025"

    def test_december_rolls_forward(self):
        s = pd.Series(["2024-12-31"])
        assert _derive_fiscal_year(s).iloc[0] == "2025"

    def test_invalid_date_returns_empty(self):
        s = pd.Series(["not-a-date"])
        assert _derive_fiscal_year(s).iloc[0] == ""

    def test_empty_string_returns_empty(self):
        s = pd.Series([""])
        assert _derive_fiscal_year(s).iloc[0] == ""

    def test_mixed_series(self):
        s = pd.Series(["2024-01-15", "2024-10-01", "", "garbage"])
        out = _derive_fiscal_year(s)
        assert list(out) == ["2024", "2025", "", ""]


# ---------------------------------------------------------------------------
# _standardize_pop_state
# ---------------------------------------------------------------------------

class TestStandardizePopState:
    def test_full_name_to_pr(self):
        s = pd.Series(["Puerto Rico"])
        assert _standardize_pop_state(s).iloc[0] == "PR"

    def test_fips_72_to_pr(self):
        s = pd.Series(["72"])
        assert _standardize_pop_state(s).iloc[0] == "PR"

    def test_already_pr_unchanged(self):
        s = pd.Series(["PR"])
        # 'PR' is not in the lowercase map, so it gets returned as-is via str().strip()
        assert _standardize_pop_state(s).iloc[0] == "PR"

    def test_other_state_unchanged(self):
        s = pd.Series(["FL"])
        assert _standardize_pop_state(s).iloc[0] == "FL"

    def test_case_insensitive(self):
        s = pd.Series(["puerto rico", "PUERTO RICO", "Puerto Rico"])
        out = _standardize_pop_state(s)
        assert all(v == "PR" for v in out)

    def test_preserves_nan(self):
        s = pd.Series([None, float("nan")])
        out = _standardize_pop_state(s)
        # NaN/None passed through (function returns val for NaN)
        assert pd.isna(out.iloc[0]) or out.iloc[0] is None
