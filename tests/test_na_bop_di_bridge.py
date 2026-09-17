from __future__ import annotations

import csv
from decimal import Decimal
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "data" / "staging" / "processed" / "macro" / "pr_na_bop_di_bridge_v0.csv"


def _rows() -> list[dict[str, str]]:
    with LEDGER.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def test_bridge_covers_current_overlap_without_equating_domains() -> None:
    rows = _rows()
    assert [int(row["fiscal_year"]) for row in rows] == [2021, 2022, 2023, 2024, 2025]
    assert all(row["state"] == "NONCOMPARABLE_AS_IDENTITY" for row in rows)


def test_bop_and_national_account_values_remain_distinct_each_year() -> None:
    for row in _rows():
        na = Decimal(row["na_di_profits_millions"])
        bop = Decimal(row["bop_di_income_debit_millions"])
        delta = Decimal(row["delta_bop_minus_na_millions"])
        assert bop != na
        assert bop - na == delta
        assert delta > 0


def test_fy2025_control_delta_is_preserved() -> None:
    row = next(row for row in _rows() if row["fiscal_year"] == "2025")
    assert Decimal(row["na_di_profits_millions"]) == Decimal("41664.1")
    assert Decimal(row["bop_di_income_debit_millions"]) == Decimal("43249.7")
    assert Decimal(row["delta_bop_minus_na_millions"]) == Decimal("1585.6")
    assert Decimal(row["delta_pct_of_na"]) == Decimal("3.806")


def test_fy2021_stale_macro_context_warning_survives() -> None:
    row = next(row for row in _rows() if row["fiscal_year"] == "2021")
    assert "stale" in row["notes"].lower()
    assert "revised macro denominator" in row["notes"].lower()
