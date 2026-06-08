"""Retry helper with jittered exponential backoff.

Stdlib only. No secrets ever logged. Used by future ingestion scripts that
hit external endpoints; behavior is configurable per call.
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
