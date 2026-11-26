"""Shared guards for the financial-intelligence candidate layer."""

from __future__ import annotations

from datetime import date

from moneysweep.capital_control.resolution_core import (
    BINDING_BASES,
    CertificationState,
    EvidenceBasis,
)

BASELINE_YEAR = 1898


class FinancialIntelligenceError(ValueError):
    """A failed identity, evidence, temporal or conservation gate."""


def require_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise FinancialIntelligenceError(f"missing {field}")
    return value


def parse_date(value: str | None, field: str) -> date | None:
    """Parse a full ISO date; an unknown date stays None and is never guessed."""
    if value is None:
        return None
    try:
        return date.fromisoformat(require_text(value, field))
    except ValueError as exc:
        raise FinancialIntelligenceError(f"{field} must be an ISO date (YYYY-MM-DD)") from exc


def check_interval(valid_from: str | None, valid_to: str | None) -> None:
    start = parse_date(valid_from, "valid_from")
    end = parse_date(valid_to, "valid_to")
    if start is not None and end is not None and end < start:
        raise FinancialIntelligenceError("valid_to cannot precede valid_from")


def check_temporal_scope(value: str | None, justification: str | None, field: str) -> None:
    """Evidence dated before the 1898 baseline needs a recorded justification."""
    parsed = parse_date(value, field)
    if parsed is None or parsed.year >= BASELINE_YEAR:
        return
    if justification is None or not justification.strip():
        raise FinancialIntelligenceError(
            f"{field} predates {BASELINE_YEAR}; a continuity justification is required"
        )


def promotable(evidence_basis: EvidenceBasis, state: CertificationState) -> bool:
    """Only binding evidence in PASS state may support a derived statement."""
    return state is CertificationState.PASS and evidence_basis in BINDING_BASES


def active_on(valid_from: str | None, valid_to: str | None, on: str) -> bool:
    """True when the known bounds do not exclude the date. Both ends are inclusive."""
    day = parse_date(on, "on")
    start = parse_date(valid_from, "valid_from")
    end = parse_date(valid_to, "valid_to")
    assert day is not None
    return (start is None or start <= day) and (end is None or day <= end)
