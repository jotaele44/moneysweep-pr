from decimal import Decimal

import pytest

from moneysweep.capital_flow import arithmetic_closure, derive_gdp_gnp_gap, retention_rates


def test_gdp_gnp_gap_is_pure_arithmetic_not_causal_label() -> None:
    assert derive_gdp_gnp_gap("129368500000", "87571200000") == Decimal("41797300000")


def test_arithmetic_closure_passes_only_when_total_conserves() -> None:
    closed = arithmetic_closure(total=100, classified=75, unclassified=25)
    assert closed.closed is True

    open_result = arithmetic_closure(total=100, classified=75, unclassified=20)
    assert open_result.closed is False


def test_unknown_destination_is_not_coerced_to_zero() -> None:
    assert retention_rates(total_value=100, resident_retained=None, nonresident_accrual=100) is None
    assert retention_rates(total_value=100, resident_retained=100, nonresident_accrual=None) is None


def test_retention_rates_require_destination_arithmetic_closure() -> None:
    assert retention_rates(total_value=100, resident_retained=60, nonresident_accrual=30) is None
    rates = retention_rates(total_value=100, resident_retained=60, nonresident_accrual=40)
    assert rates == (Decimal("0.6"), Decimal("0.4"))


def test_retention_rejects_nonpositive_denominator() -> None:
    with pytest.raises(ValueError):
        retention_rates(total_value=0, resident_retained=0, nonresident_accrual=0)
