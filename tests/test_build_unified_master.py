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
    run,
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


def test_run_adds_parent_lineage_to_entity_master(tmp_path: Path):
    processed = tmp_path / "data" / "staging" / "processed"
    enrichment = processed / "enrichment"
    processed.mkdir(parents=True, exist_ok=True)
    enrichment.mkdir(parents=True, exist_ok=True)

    pd.DataFrame(
        [
            {
                "contract_id": "C-1",
                "vendor_name": "Acme LLC",
                "agency_name": "FEMA",
                "award_date": "2024-01-15",
                "obligated_amount": "1000",
                "pop_state": "PR",
                "source_file": "contracts.csv",
                "fiscal_year": "2024",
            },
            {
                "contract_id": "C-2",
                "vendor_name": "Acme LLC",
                "agency_name": "FEMA",
                "award_date": "2024-02-10",
                "obligated_amount": "500",
                "pop_state": "PR",
                "source_file": "contracts.csv",
                "fiscal_year": "2024",
            },
        ]
    ).to_csv(processed / "pr_contracts_master.csv", index=False)

    pd.DataFrame(
        [
            {
                "vendor_name": "Acme LLC",
                "uei": "UEI-ACME-CHILD",
                "parent_uei": "UEI-ACME-PARENT",
                "parent_name": "Acme Holdings",
            }
        ]
    ).to_csv(enrichment / "entity_hierarchy.csv", index=False)

    summary = run(root=tmp_path)
    entity_master = pd.read_csv(processed / "entity_master.csv", dtype=str).fillna("")

    assert summary["entity_master_quality"]["parent_uei_coverage"] == 1.0
    assert summary["entity_master_quality"]["recipient_uei_coverage"] == 1.0

    row = entity_master.iloc[0]
    assert row["entity_key"] == "ACME"
    assert row["recipient_uei"] == "UEI-ACME-CHILD"
    assert row["parent_uei"] == "UEI-ACME-PARENT"
    assert row["parent_name"] == "Acme Holdings"
    assert row["resolved_entity_name"] == "Acme Holdings"
    assert row["resolved_entity_key"] == "ACME HOLDINGS"
