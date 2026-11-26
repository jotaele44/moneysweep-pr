"""Financial and economic intelligence layer (candidate, not adopted).

An additive classification and conservation layer over the existing MoneySweep
primitives. It introduces no second identity engine: identity adjudication stays
in `moneysweep.capital_control.resolution_core`, relationships stay in
`moneysweep.entity_network`, and amounts stay bound to source rows through
`moneysweep.financial_classification_v1`.
"""

from ._common import BASELINE_YEAR, FinancialIntelligenceError
from .continuity import (
    CONFLICT,
    DIMENSIONS,
    UNKNOWN,
    ContinuityObservation,
    DimensionStatus,
    continuity_profile,
)
from .ontology import (
    DOMAIN_IDS,
    OntologyError,
    load_ontology,
    unresolved_foundation_bindings,
    validate_ontology,
)
from .ownership import (
    HolderPath,
    InterestKind,
    OwnershipInterval,
    Terminal,
    assert_share_conservation,
    holders_at,
    resolve_ultimate_holders,
)
from .transactions import (
    Disclosure,
    DomainMembership,
    FlowCharacter,
    FlowCharacterAssertion,
    FlowDirection,
    Transaction,
    TransactionEquivalence,
    canonical_ids,
    character_conflicts,
    domain_rollup,
    geographic_direction,
    make_transaction,
    non_cash_ids,
    project_domains,
    transaction_id,
    unique_total,
    validate_memberships,
)

__all__ = [
    "BASELINE_YEAR",
    "CONFLICT",
    "DIMENSIONS",
    "DOMAIN_IDS",
    "UNKNOWN",
    "ContinuityObservation",
    "DimensionStatus",
    "Disclosure",
    "DomainMembership",
    "FinancialIntelligenceError",
    "FlowCharacter",
    "FlowCharacterAssertion",
    "FlowDirection",
    "HolderPath",
    "InterestKind",
    "OntologyError",
    "OwnershipInterval",
    "Terminal",
    "Transaction",
    "TransactionEquivalence",
    "assert_share_conservation",
    "canonical_ids",
    "character_conflicts",
    "continuity_profile",
    "domain_rollup",
    "geographic_direction",
    "holders_at",
    "load_ontology",
    "make_transaction",
    "non_cash_ids",
    "project_domains",
    "resolve_ultimate_holders",
    "transaction_id",
    "unique_total",
    "unresolved_foundation_bindings",
    "validate_memberships",
    "validate_ontology",
]
