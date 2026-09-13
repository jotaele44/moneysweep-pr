from __future__ import annotations

from dataclasses import dataclass

from .models import CertificationState


PUBLIC_CLOSED_STATES = {
    CertificationState.PASS,
    CertificationState.NEGATIVELY_CLOSED,
    CertificationState.DEMONSTRABLY_INACCESSIBLE,
}


@dataclass(frozen=True)
class UnlockResult:
    state: CertificationState
    missing: tuple[str, ...]


@dataclass(frozen=True)
class DenominatorResult:
    state: CertificationState
    blockers: tuple[str, ...]


def evaluate_unlock(
    required: tuple[str, ...], states: dict[str, CertificationState]
) -> UnlockResult:
    missing = tuple(name for name in required if states.get(name) not in PUBLIC_CLOSED_STATES)
    return UnlockResult(
        CertificationState.PASS if not missing else CertificationState.BLOCKED,
        missing,
    )


def parcel_unlock(states: dict[str, CertificationState]) -> UnlockResult:
    return evaluate_unlock(("authoritative_property_anchor",), states)


def federation_unlock(states: dict[str, CertificationState]) -> UnlockResult:
    return evaluate_unlock(("stable_id_bridge",), states)


def funding_unlock(states: dict[str, CertificationState]) -> UnlockResult:
    return evaluate_unlock(("project_specific_binding",), states)


def evaluate_public_denominator(
    source_states: dict[str, CertificationState],
) -> DenominatorResult:
    blockers = tuple(
        sorted(name for name, state in source_states.items() if state not in PUBLIC_CLOSED_STATES)
    )
    return DenominatorResult(
        CertificationState.PASS if not blockers else CertificationState.BLOCKED,
        blockers,
    )


def evaluate_foia_gate(
    source_states: dict[str, CertificationState],
) -> DenominatorResult:
    return evaluate_public_denominator(source_states)
