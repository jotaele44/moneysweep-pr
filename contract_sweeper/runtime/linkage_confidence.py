"""Link-confidence scoring for joining sub-awards to prime awards.

Confidence is a weighted sum of independent join signals. Each weight is
documented inline; the function is deterministic and returns values in
[0.0, 1.0].

`requires_manual_review` is a derived bool used to route low-confidence
joins to the review queue.
"""
from __future__ import annotations

from dataclasses import dataclass

MANUAL_REVIEW_THRESHOLD = 0.90


@dataclass(frozen=True)
class LinkSignals:
    """Boolean signals that contribute to a subaward link score."""

    has_prime_award_id: bool = False
    has_prime_name: bool = False
    has_sub_name: bool = False
    has_prime_uei: bool = False
    has_sub_uei: bool = False
    has_award_id_match_in_master: bool = False


# Weights sum to <=1.0 by design; missing signals leave room for partial joins.
_WEIGHT_PRIME_AWARD_ID = 0.30
_WEIGHT_PRIME_NAME = 0.20
_WEIGHT_SUB_NAME = 0.20
_WEIGHT_PRIME_UEI = 0.15
_WEIGHT_SUB_UEI = 0.15


def score_subaward_link(signals: LinkSignals) -> float:
    """Return [0.0, 1.0] confidence from boolean join signals."""
    score = 0.0
    if signals.has_prime_award_id:
        score += _WEIGHT_PRIME_AWARD_ID
    if signals.has_prime_name:
        score += _WEIGHT_PRIME_NAME
    if signals.has_sub_name:
        score += _WEIGHT_SUB_NAME
    if signals.has_prime_uei:
        score += _WEIGHT_PRIME_UEI
    if signals.has_sub_uei:
        score += _WEIGHT_SUB_UEI
    # award-id existing in the master table is a multiplicative trust boost,
    # but it only matters when paired with a prime_award_id signal.
    if signals.has_prime_award_id and signals.has_award_id_match_in_master:
        score = min(1.0, score + 0.05)
    return round(min(score, 1.0), 3)


def requires_manual_review(confidence: float, threshold: float = MANUAL_REVIEW_THRESHOLD) -> bool:
    """True if a confidence falls below the manual-review threshold."""
    return confidence < threshold
