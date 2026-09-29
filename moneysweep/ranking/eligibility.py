"""Fail-closed eligibility gate for financial ranking inputs.

This module decides whether one source observation may enter a ranking universe.
It does not resolve identity and does not assign ranks.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Mapping

PASS_IDENTITY_STATES = {"PASS", "CERTIFIED"}
PASS_BINDING_BASES = {"STABLE_ID", "AUTHORITATIVE_BINDING", "CERTIFIED_GEOMETRY"}
DISALLOWED_ORIGINS = {"SEED", "FALLBACK_SEED", "SYNTHETIC", "ESTIMATE", "UNKNOWN"}


@dataclass(frozen=True)
class EligibilityDecision:
    eligible: bool
    state: str
    reasons: tuple[str, ...]
    metric_value: Decimal | None


def _text(row: Mapping[str, object], key: str) -> str:
    value = row.get(key)
    return "" if value is None else str(value).strip()


def evaluate_ranking_row(row: Mapping[str, object]) -> EligibilityDecision:
    """Evaluate a financial observation without inferring missing evidence.

    Required evidence is intentionally explicit. Names, normalized names,
    proximity, row ordering, and source presence are never identity proof.
    """
    reasons: list[str] = []

    identity_state = _text(row, "identity_state").upper()
    binding_basis = _text(row, "binding_basis").upper()
    stable_id = _text(row, "stable_id")
    origin = _text(row, "origin").upper()

    if identity_state not in PASS_IDENTITY_STATES:
        reasons.append("IDENTITY_NOT_CERTIFIED")
    if binding_basis not in PASS_BINDING_BASES:
        reasons.append("BINDING_BASIS_INELIGIBLE")
    if not stable_id:
        reasons.append("STABLE_ID_MISSING")
    if not origin:
        reasons.append("ORIGIN_MISSING")
    elif origin in DISALLOWED_ORIGINS:
        reasons.append("ORIGIN_INELIGIBLE")

    for key, reason in (
        ("source_id", "SOURCE_ID_MISSING"),
        ("source_snapshot_sha256", "SOURCE_SNAPSHOT_HASH_MISSING"),
        ("metric_name", "METRIC_NAME_MISSING"),
        ("metric_unit", "METRIC_UNIT_MISSING"),
        ("period_start", "PERIOD_START_MISSING"),
        ("period_end", "PERIOD_END_MISSING"),
        ("geographic_scope", "GEOGRAPHIC_SCOPE_MISSING"),
    ):
        if not _text(row, key):
            reasons.append(reason)

    raw_value = _text(row, "metric_value")
    metric_value: Decimal | None = None
    if not raw_value:
        reasons.append("METRIC_VALUE_MISSING")
    else:
        try:
            metric_value = Decimal(raw_value)
            if not metric_value.is_finite():
                reasons.append("METRIC_VALUE_NONFINITE")
                metric_value = None
        except InvalidOperation:
            reasons.append("METRIC_VALUE_INVALID")

    if reasons:
        return EligibilityDecision(False, "BLOCKED", tuple(reasons), metric_value)
    return EligibilityDecision(True, "PASS", (), metric_value)
