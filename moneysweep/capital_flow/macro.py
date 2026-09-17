from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Iterable


class MacroCandidateState(StrEnum):
    CURRENT = "CURRENT"
    HISTORICAL = "HISTORICAL"
    SUPERSEDED = "SUPERSEDED"
    UNRESOLVED = "UNRESOLVED"


class MacroClosureState(StrEnum):
    EXACT = "EXACT"
    WITHIN_DECLARED_ROUNDING_BUDGET = "WITHIN_DECLARED_ROUNDING_BUDGET"
    FAIL = "FAIL"
    UNRESOLVED = "UNRESOLVED"


@dataclass(frozen=True)
class MacroObservation:
    observation_id: str
    fiscal_year: int
    manifestation_id: str
    source_table: str
    publication_vintage: str
    gnp_millions: Decimal
    gdp_millions: Decimal
    reported_less_rest_of_world_millions: Decimal | None
    candidate_state: MacroCandidateState

    @property
    def computed_gap_millions(self) -> Decimal:
        return self.gdp_millions - self.gnp_millions


@dataclass(frozen=True)
class MacroIdentityClosure:
    computed_gap_millions: Decimal
    reported_gap_millions: Decimal | None
    delta_millions: Decimal | None
    rounding_budget_millions: Decimal
    state: MacroClosureState


def published_identity_closure(
    *,
    gdp_millions: Decimal,
    gnp_millions: Decimal,
    reported_gap_millions: Decimal | None,
    published_precision_millions: Decimal = Decimal("0.1"),
) -> MacroIdentityClosure:
    """Check GDP - GNP against a published gap without hiding source rounding.

    For three independently rounded one-decimal quantities, the worst-case
    subtraction identity error is 1.5 times the published precision. Exact
    equality remains distinct from tolerance-based closure.
    """

    computed = gdp_millions - gnp_millions
    budget = published_precision_millions * Decimal("1.5")
    if reported_gap_millions is None:
        return MacroIdentityClosure(
            computed_gap_millions=computed,
            reported_gap_millions=None,
            delta_millions=None,
            rounding_budget_millions=budget,
            state=MacroClosureState.UNRESOLVED,
        )

    delta = computed - reported_gap_millions
    if delta == 0:
        state = MacroClosureState.EXACT
    elif abs(delta) <= budget:
        state = MacroClosureState.WITHIN_DECLARED_ROUNDING_BUDGET
    else:
        state = MacroClosureState.FAIL

    return MacroIdentityClosure(
        computed_gap_millions=computed,
        reported_gap_millions=reported_gap_millions,
        delta_millions=delta,
        rounding_budget_millions=budget,
        state=state,
    )


def adjudicate_latest_manifestation(
    observations: Iterable[MacroObservation],
) -> MacroObservation | None:
    """Return a canonical annual observation only when latest evidence agrees.

    Older manifestations may be preserved as historical/superseded. If the
    latest publication vintage contains multiple non-superseded candidates with
    different GDP or GNP values, fail closed and return None. Deterministic row
    ordering is used only after the values agree; it is not identity evidence.
    """

    rows = [row for row in observations if row.candidate_state != MacroCandidateState.SUPERSEDED]
    if not rows:
        return None

    latest_vintage = max(row.publication_vintage for row in rows)
    latest = [row for row in rows if row.publication_vintage == latest_vintage]
    value_pairs = {(row.gdp_millions, row.gnp_millions) for row in latest}
    if len(value_pairs) != 1:
        return None

    return sorted(latest, key=lambda row: (row.source_table, row.observation_id))[0]
