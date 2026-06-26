"""Jitter/backoff bounds + circuit-breaker tests for retry_runtime (Wave M, task 71).

Complements the basic retry coverage in tests/test_runtime_helpers.py with
property-style bounds on the backoff delay and full state-machine coverage of
the new CircuitBreaker. Time is injected, so nothing actually sleeps.
"""

from __future__ import annotations

import pytest

from moneysweep.runtime.retry_runtime import (
    CircuitBreaker,
    CircuitOpen,
    RetryPolicy,
    _compute_delay,
)


# --------------------------------------------------------------------------- #
# Jitter / backoff bounds
# --------------------------------------------------------------------------- #


@pytest.mark.unit
@pytest.mark.parametrize("attempt", [1, 2, 3, 4, 5, 8])
def test_delay_stays_within_jitter_band_of_capped_expo(attempt):
    policy = RetryPolicy(base_delay_seconds=1.0, max_delay_seconds=30.0, jitter_fraction=0.25)
    capped = min(policy.base_delay_seconds * (2 ** (attempt - 1)), policy.max_delay_seconds)
    low = capped * (1 - policy.jitter_fraction)
    high = capped * (1 + policy.jitter_fraction)
    # Sample many times; every draw must land in the jitter band.
    for _ in range(200):
        d = _compute_delay(attempt, policy)
        assert low <= d <= high


@pytest.mark.unit
def test_backoff_is_monotonic_until_cap_at_midpoints():
    """Without jitter the midpoint delay doubles each attempt until the cap."""
    policy = RetryPolicy(base_delay_seconds=1.0, max_delay_seconds=30.0, jitter_fraction=0.0)
    midpoints = [_compute_delay(a, policy) for a in range(1, 7)]
    assert midpoints[:5] == [1.0, 2.0, 4.0, 8.0, 16.0]
    assert midpoints[5] == 30.0  # 32 capped to 30
    # Non-decreasing throughout.
    assert all(b >= a for a, b in zip(midpoints, midpoints[1:]))


@pytest.mark.unit
def test_delay_never_exceeds_cap_plus_jitter():
    policy = RetryPolicy(base_delay_seconds=2.0, max_delay_seconds=10.0, jitter_fraction=0.5)
    hard_ceiling = policy.max_delay_seconds * (1 + policy.jitter_fraction)
    for attempt in range(1, 12):
        for _ in range(50):
            assert _compute_delay(attempt, policy) <= hard_ceiling


# --------------------------------------------------------------------------- #
# CircuitBreaker state machine (injected clock — deterministic)
# --------------------------------------------------------------------------- #


class _Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


def _boom():
    raise RuntimeError("upstream down")


@pytest.mark.unit
def test_starts_closed_and_passes_through_success():
    cb = CircuitBreaker(failure_threshold=3, reset_timeout=10.0, clock=_Clock())
    assert cb.state == "closed"
    assert cb.call(lambda: "ok") == "ok"
    assert cb.state == "closed"


@pytest.mark.unit
def test_opens_after_threshold_consecutive_failures():
    cb = CircuitBreaker(failure_threshold=3, reset_timeout=10.0, clock=_Clock())
    for _ in range(3):
        with pytest.raises(RuntimeError):
            cb.call(_boom)
    # Threshold reached → open, and further calls short-circuit without calling fn.
    assert cb.state == "open"
    called = False

    def _tracker():
        nonlocal called
        called = True
        return "x"

    with pytest.raises(CircuitOpen):
        cb.call(_tracker)
    assert called is False


@pytest.mark.unit
def test_success_resets_failure_count_before_threshold():
    cb = CircuitBreaker(failure_threshold=3, reset_timeout=10.0, clock=_Clock())
    for _ in range(2):
        with pytest.raises(RuntimeError):
            cb.call(_boom)
    assert cb.call(lambda: "ok") == "ok"  # resets the streak
    assert cb.state == "closed"
    # Two more failures should NOT open it (count was reset).
    for _ in range(2):
        with pytest.raises(RuntimeError):
            cb.call(_boom)
    assert cb.state == "closed"


@pytest.mark.unit
def test_half_opens_after_cooldown_then_closes_on_probe_success():
    clock = _Clock()
    cb = CircuitBreaker(failure_threshold=2, reset_timeout=10.0, clock=clock)
    for _ in range(2):
        with pytest.raises(RuntimeError):
            cb.call(_boom)
    assert cb.state == "open"

    clock.advance(10.0)  # cooldown elapsed
    assert cb.state == "half_open"

    # A successful probe closes the circuit and clears state.
    assert cb.call(lambda: "recovered") == "recovered"
    assert cb.state == "closed"


@pytest.mark.unit
def test_half_open_probe_failure_reopens_with_fresh_cooldown():
    clock = _Clock()
    cb = CircuitBreaker(failure_threshold=2, reset_timeout=10.0, clock=clock)
    for _ in range(2):
        with pytest.raises(RuntimeError):
            cb.call(_boom)
    clock.advance(10.0)
    assert cb.state == "half_open"

    # Probe fails → reopen, cooldown restarts from now.
    with pytest.raises(RuntimeError):
        cb.call(_boom)
    assert cb.state == "open"
    clock.advance(9.9)
    assert cb.state == "open"
    clock.advance(0.1)
    assert cb.state == "half_open"


@pytest.mark.unit
def test_fail_on_narrows_which_exceptions_trip_the_breaker():
    cb = CircuitBreaker(failure_threshold=2, reset_timeout=10.0, clock=_Clock())

    def _key_error():
        raise KeyError("not a network failure")

    # Only ConnectionError trips it; KeyError propagates without counting.
    for _ in range(3):
        with pytest.raises(KeyError):
            cb.call(_key_error, fail_on=(ConnectionError,))
    assert cb.state == "closed"
