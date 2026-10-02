"""Evidence-gated ranking primitives for MoneySweep."""

from .eligibility import EligibilityDecision, evaluate_ranking_row

__all__ = ["EligibilityDecision", "evaluate_ranking_row"]
