from __future__ import annotations

from dataclasses import dataclass

from .models import CertificationState, FinancialAmount


AMOUNT_SEMANTICS = {
    "PROJECT_ESTIMATE",
    "CONTRACT_AMOUNT",
    "MAX_PAYABLE",
    "GRANT_AUTHORIZED",
    "OBLIGATION",
    "DISBURSEMENT",
    "INVOICE",
    "PAYMENT",
    "CANCELLATION",
    "BALANCE",
}


def validate_amount(amount: FinancialAmount) -> FinancialAmount:
    if amount.semantics not in AMOUNT_SEMANTICS:
        raise ValueError(f"unsupported amount semantics: {amount.semantics}")
    if amount.value < 0:
        raise ValueError("financial amount must be nonnegative")
    return amount


@dataclass(frozen=True)
class GrantClosure:
    state: CertificationState
    authorized: float
    disbursed: float
    cancelled: float
    balance: float
    delta: float


def close_grant(
    *,
    authorized: float,
    disbursed: float,
    cancelled: float,
    balance: float,
    tolerance: float = 1e-6,
) -> GrantClosure:
    for value in (authorized, disbursed, cancelled, balance):
        if value < 0:
            raise ValueError("grant values must be nonnegative")
    delta = authorized - (disbursed + cancelled + balance)
    state = CertificationState.PASS if abs(delta) <= tolerance else CertificationState.FAIL
    return GrantClosure(state, authorized, disbursed, cancelled, balance, delta)
