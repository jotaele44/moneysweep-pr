from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "data" / "manifests" / "macro" / "jp_bop_iip_lineage_v1.json"


def _manifest() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def test_current_bop_di_series_covers_fy2018_2025() -> None:
    series = _manifest()["current_2025_vintage_direct_investment_income_debit_millions"]
    assert set(series) == {str(year) for year in range(2018, 2026)}
    assert Decimal(str(series["2025"])) == Decimal("43249.7")


def test_revised_vintages_are_preserved_not_overwritten() -> None:
    revisions = {row["fiscal_year"]: row for row in _manifest()["revision_observations"]}
    assert Decimal(str(revisions[2023]["bop_2024_publication_millions"])) == Decimal("39092.0")
    assert Decimal(str(revisions[2023]["bop_2025_publication_millions"])) == Decimal("38865.2")
    assert Decimal(str(revisions[2023]["delta_millions"])) == Decimal("-226.8")
    assert revisions[2023]["state"] == "REVISED_PRESERVE_BOTH"

    assert Decimal(str(revisions[2024]["bop_2024_publication_millions"])) == Decimal("42530.6")
    assert Decimal(str(revisions[2024]["bop_2025_publication_millions"])) == Decimal("42332.2")
    assert Decimal(str(revisions[2024]["delta_millions"])) == Decimal("-198.4")
    assert revisions[2024]["state"] == "REVISED_PRESERVE_BOTH"


def test_unchanged_value_is_not_misclassified_as_revision() -> None:
    row = next(row for row in _manifest()["revision_observations"] if row["fiscal_year"] == 2022)
    assert row["state"] == "UNCHANGED_ACROSS_OBSERVED_VINTAGES"
    assert Decimal(str(row["delta_millions"])) == Decimal("0.0")


def test_cross_account_equivalence_remains_failed() -> None:
    check = _manifest()["cross_account_check"]
    assert check["equivalence_state"] == "FAIL_NONCOMPARABLE_AS_IDENTITY"
    assert check["diagnostic_ledger"].endswith("pr_na_bop_di_bridge_v0.csv")
