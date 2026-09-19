from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum


class MeasurementType(StrEnum):
    FLOW = "FLOW"
    STOCK = "STOCK"
    RATE = "RATE"
    BALANCE = "BALANCE"
    VALUATION = "VALUATION"
    COUNT = "COUNT"
    UNKNOWN = "UNKNOWN"


class FlowDirection(StrEnum):
    INTO_PR = "INTO_PR"
    WITHIN_PR = "WITHIN_PR"
    OUT_OF_PR = "OUT_OF_PR"
    THROUGH_PR = "THROUGH_PR"
    UNKNOWN = "UNKNOWN"


class RetentionState(StrEnum):
    RETAINED_PR = "RETAINED_PR"
    ACCRUES_NONRESIDENT = "ACCRUES_NONRESIDENT"
    MIXED = "MIXED"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    UNKNOWN = "UNKNOWN"


class CertificationState(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    OPEN = "OPEN"
    BLOCKED = "BLOCKED"
    PROVISIONAL = "PROVISIONAL"
    AUDIT_ONLY = "AUDIT_ONLY"
    NONCANONICAL = "NONCANONICAL"
    CANDIDATE_NOT_IDENTITY = "CANDIDATE_NOT_IDENTITY"
    UNRESOLVED = "UNRESOLVED"
    SUPERSEDED = "SUPERSEDED"


@dataclass(frozen=True)
class ClosureResult:
    total: Decimal
    classified: Decimal
    unclassified: Decimal
    closed: bool


def _decimal(value: int | float | str | Decimal) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def derive_gdp_gnp_gap(
    gdp: int | float | str | Decimal,
    gnp: int | float | str | Decimal,
) -> Decimal:
    """Return GDP - GNP without assigning a causal or destination interpretation."""

    return _decimal(gdp) - _decimal(gnp)


def arithmetic_closure(
    *,
    total: int | float | str | Decimal,
    classified: int | float | str | Decimal,
    unclassified: int | float | str | Decimal,
) -> ClosureResult:
    """Require explicit classified + unclassified conservation for a bounded node."""

    total_d = _decimal(total)
    classified_d = _decimal(classified)
    unclassified_d = _decimal(unclassified)
    return ClosureResult(
        total=total_d,
        classified=classified_d,
        unclassified=unclassified_d,
        closed=classified_d + unclassified_d == total_d,
    )


def retention_rates(
    *,
    total_value: int | float | str | Decimal,
    resident_retained: int | float | str | Decimal | None,
    nonresident_accrual: int | float | str | Decimal | None,
) -> tuple[Decimal, Decimal] | None:
    """Return retention/external-capture rates only when the bounded destination closes.

    UNKNOWN is not coerced to zero. If either destination amount is unresolved, or if
    resident + nonresident does not equal the bounded total exactly, return None.
    """

    if resident_retained is None or nonresident_accrual is None:
        return None

    total_d = _decimal(total_value)
    resident_d = _decimal(resident_retained)
    external_d = _decimal(nonresident_accrual)
    if total_d <= 0:
        raise ValueError("total_value must be positive")
    if resident_d < 0 or external_d < 0:
        raise ValueError("destination amounts must be non-negative")
    if resident_d + external_d != total_d:
        return None

    return resident_d / total_d, external_d / total_d
