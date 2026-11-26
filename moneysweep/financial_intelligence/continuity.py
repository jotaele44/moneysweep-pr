"""Corporate continuity: seven status dimensions that never imply one another.

A bankrupt organization may keep assets that another entity operates. Each
dimension is therefore observed on its own evidence; a dimension with no
promotable observation is UNKNOWN, not copied from a neighbouring dimension.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass

from moneysweep.capital_control.resolution_core import CertificationState, EvidenceBasis

from ._common import (
    FinancialIntelligenceError,
    active_on,
    check_interval,
    check_temporal_scope,
    promotable,
    require_text,
)

DIMENSIONS: dict[str, frozenset[str]] = {
    "LEGAL": frozenset({"ACTIVE", "DISSOLVED", "MERGED", "SUSPENDED"}),
    "FINANCIAL": frozenset({"SOLVENT", "INSOLVENT", "BANKRUPT", "RESTRUCTURING"}),
    "OPERATIONAL": frozenset({"ACTIVE", "INACTIVE", "PARTIALLY_ACTIVE"}),
    "ASSET_OWNERSHIP": frozenset({"RETAINED", "TRANSFERRED", "LIQUIDATED", "UNRESOLVED"}),
    "ASSET_OPERATION": frozenset(
        {"OWNER_OPERATED", "LEASED", "CONCESSION_OPERATED", "THIRD_PARTY_OPERATED"}
    ),
    "CORPORATE_CONTROL": frozenset({"ORIGINAL", "SUCCESSOR", "TRUSTEE", "CREDITOR", "GOVERNMENT"}),
    "REVENUE": frozenset({"ACTIVE", "REDIRECTED", "DISCONTINUED", "UNDISCLOSED"}),
}
UNKNOWN = "UNKNOWN"
CONFLICT = "CONFLICT"


@dataclass(frozen=True)
class ContinuityObservation:
    """One sourced statement about one dimension of one entity."""

    observation_id: str
    entity_ref: str
    dimension: str
    status: str
    source_manifestation_id: str
    evidence_basis: EvidenceBasis = EvidenceBasis.NONE
    state: CertificationState = CertificationState.UNRESOLVED
    valid_from: str | None = None
    valid_to: str | None = None
    pre_baseline_justification: str | None = None

    def __post_init__(self) -> None:
        require_text(self.observation_id, "observation_id")
        require_text(self.entity_ref, "entity_ref")
        require_text(self.source_manifestation_id, "source_manifestation_id")
        if self.dimension not in DIMENSIONS:
            raise FinancialIntelligenceError(f"unknown continuity dimension {self.dimension}")
        if self.status not in DIMENSIONS[self.dimension]:
            raise FinancialIntelligenceError(f"{self.status} is not a {self.dimension} status")
        check_interval(self.valid_from, self.valid_to)
        check_temporal_scope(self.valid_from, self.pre_baseline_justification, "valid_from")


@dataclass(frozen=True)
class DimensionStatus:
    status: str
    supporting_observation_ids: tuple[str, ...] = ()
    unpromoted_candidates: tuple[str, ...] = ()


def continuity_profile(
    observations: Iterable[ContinuityObservation], entity_ref: str, on: str
) -> dict[str, DimensionStatus]:
    """Status of every dimension on a date, from that dimension's own evidence only."""
    promoted: defaultdict[str, defaultdict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    candidates: defaultdict[str, set[str]] = defaultdict(set)
    seen: set[str] = set()
    for observation in observations:
        if observation.observation_id in seen:
            raise FinancialIntelligenceError("duplicate continuity observation")
        seen.add(observation.observation_id)
        if observation.entity_ref != entity_ref:
            continue
        if not active_on(observation.valid_from, observation.valid_to, on):
            continue
        if promotable(observation.evidence_basis, observation.state):
            promoted[observation.dimension][observation.status].append(observation.observation_id)
        else:
            candidates[observation.dimension].add(observation.status)

    profile: dict[str, DimensionStatus] = {}
    for dimension in DIMENSIONS:
        statuses: dict[str, list[str]] = promoted.get(dimension, {})
        supporting = tuple(sorted(i for ids in statuses.values() for i in ids))
        if not statuses:
            status = UNKNOWN
        elif len(statuses) == 1:
            status = next(iter(statuses))
        else:
            status = CONFLICT
        profile[dimension] = DimensionStatus(
            status=status,
            supporting_observation_ids=supporting,
            unpromoted_candidates=tuple(sorted(candidates.get(dimension, ()))),
        )
    return profile
