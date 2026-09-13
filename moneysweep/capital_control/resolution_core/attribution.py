from __future__ import annotations

from dataclasses import dataclass

from .finance import validate_amount
from .models import CertificationState, FinancialAmount


@dataclass(frozen=True)
class FinancialAttribution:
    state: CertificationState
    instrument_ref: str
    project_ref: str | None
    property_ref: str | None
    amount: FinancialAmount
    reason: str


def attribute_financial_instrument(
    *,
    instrument_ref: str,
    amount: FinancialAmount,
    project_specific_binding: bool,
    project_ref: str | None = None,
    property_ref: str | None = None,
) -> FinancialAttribution:
    validated = validate_amount(amount)
    if not project_specific_binding or not project_ref:
        return FinancialAttribution(
            CertificationState.BLOCKED,
            instrument_ref,
            project_ref,
            property_ref,
            validated,
            "project-specific authoritative binding required before funding attribution",
        )
    return FinancialAttribution(
        CertificationState.PASS,
        instrument_ref,
        project_ref,
        property_ref,
        validated,
        "project-specific financial attribution accepted",
    )
