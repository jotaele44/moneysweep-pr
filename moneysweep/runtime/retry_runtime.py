"""Retry helper with jittered exponential backoff, plus a circuit breaker.

Stdlib only. No secrets ever logged. Used by future ingestion scripts that
hit external endpoints; behavior is configurable per call. The
:class:`CircuitBreaker` lets a caller stop hammering an endpoint that is failing
repeatedly (Wave M, task 71): after a run of failures it "opens" and
short-circuits further calls until a cooldown elapses, then "half-opens" to probe
recovery.
"""

from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass
from typing import Callable, TypeVar

T = TypeVar("T")

_LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 5
    base_delay_seconds: float = 1.0
    max_delay_seconds: float = 30.0
    jitter_fraction: float = 0.25


class RetryExhausted(RuntimeError):
    """Raised when all attempts fail."""


def _compute_delay(attempt: int, policy: RetryPolicy) -> float:
    expo = policy.base_delay_seconds * (2 ** (attempt - 1))
    capped = min(expo, policy.max_delay_seconds)
    jitter = capped * policy.jitter_fraction
    return capped + random.uniform(-jitter, jitter)


def with_retry(
    fn: Callable[[], T],
    *,
    policy: RetryPolicy | None = None,
    retry_on: tuple[type[BaseException], ...] = (Exception,),
    sleeper: Callable[[float], None] = time.sleep,
) -> T:
    """Invoke fn() with retry. Raises RetryExhausted after policy.max_attempts.

    `retry_on` lets callers narrow which exceptions trigger a retry (so
    programming errors like KeyError aren't swallowed indefinitely).
    """
    policy = policy or RetryPolicy()
    last_exc: BaseException | None = None
    for attempt in range(1, policy.max_attempts + 1):
        try:
            return fn()
        except retry_on as exc:
            last_exc = exc
            _LOG.warning(
                "retry attempt %d/%d failed: %s",
                attempt,
                policy.max_attempts,
                type(exc).__name__,
            )
            if attempt == policy.max_attempts:
                break
            sleeper(max(0.0, _compute_delay(attempt, policy)))
    raise RetryExhausted(
        f"all {policy.max_attempts} attempts failed; last: {type(last_exc).__name__}"
    ) from last_exc


class CircuitOpen(RuntimeError):
    """Raised by :meth:`CircuitBreaker.call` while the circuit is open."""


@dataclass
class CircuitBreaker:
    """A minimal failure circuit breaker around a callable.

    States:
      * **closed** — calls pass through; consecutive failures are counted.
      * **open** — once ``failure_threshold`` consecutive failures are reached,
        calls short-circuit with :class:`CircuitOpen` for ``reset_timeout``
        seconds (no call to ``fn`` is made).
      * **half-open** — after the cooldown, the next call is allowed through as a
        probe; success closes the circuit and clears the count, another failure
        re-opens it for a fresh cooldown.

    Pairs with :func:`with_retry`: retry handles transient blips within one
    logical call; the breaker handles a sustained outage across many calls.
    Time is injected via ``clock`` so it is deterministically testable.
    """

    failure_threshold: int = 5
    reset_timeout: float = 30.0
    clock: Callable[[], float] = time.monotonic

    _consecutive_failures: int = 0
    _opened_at: float | None = None

    @property
    def state(self) -> str:
        if self._opened_at is None:
            return "closed"
        if (self.clock() - self._opened_at) >= self.reset_timeout:
            return "half_open"
        return "open"

    def call(
        self,
        fn: Callable[[], T],
        *,
        fail_on: tuple[type[BaseException], ...] = (Exception,),
    ) -> T:
        state = self.state
        if state == "open":
            raise CircuitOpen(
                f"circuit open after {self._consecutive_failures} consecutive failures; "
                f"retry after cooldown"
            )
        try:
            result = fn()
        except fail_on as exc:
            self._record_failure()
            _LOG.warning(
                "circuit_breaker_failure",
                extra={
                    "consecutive_failures": self._consecutive_failures,
                    "state": self.state,
                    "error": type(exc).__name__,
                },
            )
            raise
        else:
            self._record_success()
            return result

    def _record_failure(self) -> None:
        self._consecutive_failures += 1
        if self._consecutive_failures >= self.failure_threshold:
            # (Re)start the cooldown window from now.
            self._opened_at = self.clock()

    def _record_success(self) -> None:
        self._consecutive_failures = 0
        self._opened_at = None
