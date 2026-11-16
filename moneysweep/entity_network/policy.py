"""Fail-closed behavioral policy for the entity-network kernel."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from typing import Hashable

from moneysweep.capital_control.resolution_core import (
    BINDING_BASES,
    Candidate,
    Cardinality,
    CertificationState,
    Resolution,
    assert_no_unsafe_many_to_many,
    resolve_candidates,
)

from .models import RelationshipAssertion, Sector, SectorMembership

_MONEY_FLOW_RELATION_TYPES = frozenset(
    {
        "PAYS",
        "RECEIVES",
        "INVESTS_IN",
        "LENDS_TO",
        "DISBURSES_TO",
        "REIMBURSES",
    }
)


def assert_no_money_flow_as_relationship(relation_type: str) -> None:
    """Reject money-movement verbs from the ordinary relationship graph."""
    token = relation_type.strip().upper()
    if token in _MONEY_FLOW_RELATION_TYPES:
        raise ValueError(f"{token} is a money-flow semantic and must use MoneyFlowObservation")


def resolve_entity_candidates(candidates: Iterable[Candidate]) -> Resolution:
    """Resolve candidates through the existing canonical resolution core."""
    return resolve_candidates(tuple(candidates))


def promotable_relationship(assertion: RelationshipAssertion) -> bool:
    """Only binding evidence in PASS state may promote an assertion."""
    assert_no_money_flow_as_relationship(assertion.relation_type)
    return assertion.state is CertificationState.PASS and assertion.evidence_basis in BINDING_BASES


def index_sector_memberships(
    memberships: Iterable[SectorMembership],
) -> dict[str, frozenset[Sector]]:
    """Return entity -> sectors without collapsing legitimate N:N membership."""
    index: defaultdict[str, set[Sector]] = defaultdict(set)
    for membership in memberships:
        index[membership.entity_id].add(membership.sector)
    return {entity_id: frozenset(sectors) for entity_id, sectors in index.items()}


def validate_membership_batch(memberships: Iterable[SectorMembership]) -> None:
    """Reject exact duplicate observations while preserving cross-sector membership."""
    seen: set[tuple[object, ...]] = set()
    for membership in memberships:
        key = (
            membership.entity_id,
            membership.sector,
            membership.role,
            membership.valid_from,
            membership.valid_to,
            membership.source_manifestation_id,
        )
        if key in seen:
            raise ValueError("duplicate sector-membership observation")
        seen.add(key)


def guard_join_cardinality(
    left_keys: Iterable[Hashable],
    right_keys: Iterable[Hashable],
) -> Cardinality:
    """Fail closed on an unintended N:N join."""
    return assert_no_unsafe_many_to_many(left_keys, right_keys)
