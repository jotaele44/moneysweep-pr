"""Canonical cross-sector entity-network kernel.

This package is additive infrastructure. It composes the existing MoneySweep
resolution core instead of introducing a second identity engine.
"""

from .models import (
    MoneyFlowObservation,
    NodeKind,
    RelationshipAssertion,
    RelationshipFamily,
    RetentionState,
    Sector,
    SectorMembership,
)
from .policy import (
    assert_no_money_flow_as_relationship,
    guard_join_cardinality,
    index_sector_memberships,
    promotable_relationship,
    resolve_entity_candidates,
    validate_membership_batch,
)

__all__ = [
    "MoneyFlowObservation",
    "NodeKind",
    "RelationshipAssertion",
    "RelationshipFamily",
    "RetentionState",
    "Sector",
    "SectorMembership",
    "assert_no_money_flow_as_relationship",
    "guard_join_cardinality",
    "index_sector_memberships",
    "promotable_relationship",
    "resolve_entity_candidates",
    "validate_membership_batch",
]
