"""Tests for the subaward linkage confidence helper."""

from __future__ import annotations

import pytest

from contract_sweeper.runtime.linkage_confidence import (
    LinkSignals,
    requires_manual_review,
    score_subaward_link,
    MANUAL_REVIEW_THRESHOLD,
)


@pytest.mark.unit
def test_no_signals_returns_zero():
    assert score_subaward_link(LinkSignals()) == 0.0


@pytest.mark.unit
def test_all_signals_returns_one():
    signals = LinkSignals(
        has_prime_award_id=True,
        has_prime_name=True,
        has_sub_name=True,
        has_prime_uei=True,
        has_sub_uei=True,
        has_award_id_match_in_master=True,
    )
    assert score_subaward_link(signals) == 1.0


@pytest.mark.unit
def test_score_is_monotonic_in_signals():
    base = LinkSignals(has_prime_award_id=True)
    with_name = LinkSignals(has_prime_award_id=True, has_prime_name=True)
    assert score_subaward_link(with_name) > score_subaward_link(base)


@pytest.mark.unit
def test_score_in_unit_interval():
    for has_pid in (True, False):
        for has_name in (True, False):
            for has_uei in (True, False):
                signals = LinkSignals(
                    has_prime_award_id=has_pid,
                    has_prime_name=has_name,
                    has_sub_name=has_name,
                    has_prime_uei=has_uei,
                    has_sub_uei=has_uei,
                )
                s = score_subaward_link(signals)
                assert 0.0 <= s <= 1.0


@pytest.mark.unit
def test_requires_manual_review_threshold():
    assert requires_manual_review(0.5) is True
    assert requires_manual_review(0.95) is False
    assert requires_manual_review(MANUAL_REVIEW_THRESHOLD) is False
