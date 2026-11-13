"""Typed primitives for the MoneySweep cross-sector entity network.

The kernel separates sector membership, non-monetary relationships, and
monetary observations. A dependency edge is not a money movement, and a
sector assignment is not an identity proof.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from moneysweep.capital_control.resolution_core import CertificationState, EvidenceBasis


class Sector(str, Enum):
    PHARMA_BIOTECH_MEDDEV = "PHARMA_BIOTECH_MEDDEV"
    AEROSPACE_DEFENSE = "AEROSPACE_DEFENSE"
    ENERGY_FUELS_GRID = "ENERGY_FUELS_GRID"
    WATER_WASTEWATER_ENVIRONMENT = "WATER_WASTEWATER_ENVIRONMENT"
    TRANSPORT_LOGISTICS = "TRANSPORT_LOGISTICS"
    TELECOM_CONNECTIVITY = "TELECOM_CONNECTIVITY"
    INDUSTRIAL_MANUFACTURING_EPC_CONSTRUCTION = "INDUSTRIAL_MANUFACTURING_EPC_CONSTRUCTION"
    GOVERNANCE_PUBLIC_FINANCE_OVERSIGHT = "GOVERNANCE_PUBLIC_FINANCE_OVERSIGHT"
    RESEARCH_ACADEMIA_WORKFORCE = "RESEARCH_ACADEMIA_WORKFORCE"
    HEALTHCARE_PAYERS_PHARMACY = "HEALTHCARE_PAYERS_PHARMACY"
    BANKING_INSURANCE_PRIVATE_FINANCE = "BANKING_INSURANCE_PRIVATE_FINANCE"
    REAL_ESTATE_TOURISM_HOSPITALITY = "REAL_ESTATE_TOURISM_HOSPITALITY"
    RETAIL_WHOLESALE_CONSUMER_DISTRIBUTION = "RETAIL_WHOLESALE_CONSUMER_DISTRIBUTION"
    TECHNOLOGY_IT_BPO_PROFESSIONAL_SERVICES = "TECHNOLOGY_IT_BPO_PROFESSIONAL_SERVICES"
    AGRICULTURE_FOOD_BEVERAGE = "AGRICULTURE_FOOD_BEVERAGE"


class NodeKind(str, Enum):
    ENTITY = "ENTITY"
    FACILITY = "FACILITY"
    PLACE = "PLACE"
    PROGRAM = "PROGRAM"
    CONTRACT = "CONTRACT"
    AWARD = "AWARD"
    ASSET = "ASSET"
    PERSON = "PERSON"


class RelationshipFamily(str, Enum):
    IDENTITY_LINEAGE = "IDENTITY_LINEAGE"
    OWNERSHIP_CONTROL = "OWNERSHIP_CONTROL"
    FACILITY = "FACILITY"
    PROCUREMENT = "PROCUREMENT"
    REGULATORY = "REGULATORY"
    INFRASTRUCTURE = "INFRASTRUCTURE"
    GOVERNANCE = "GOVERNANCE"
    RESEARCH_WORKFORCE = "RESEARCH_WORKFORCE"


class RetentionState(str, Enum):
    PR_RETAINED_SUPPORTED = "PR_RETAINED_SUPPORTED"
    PR_OUTFLOW_SUPPORTED = "PR_OUTFLOW_SUPPORTED"
    MIXED = "MIXED"
    INDETERMINATE = "INDETERMINATE"
    NOT_APPLICABLE = "NOT_APPLICABLE"


def _validate_interval(valid_from: str | None, valid_to: str | None) -> None:
    if valid_from is not None and valid_to is not None and valid_to < valid_from:
        raise ValueError("valid_to cannot precede valid_from")


@dataclass(frozen=True)
class SectorMembership:
    """Evidence-backed N:N membership between a canonical entity and a sector."""

    entity_id: str
    sector: Sector
    role: str
    source_manifestation_id: str
    evidence_basis: EvidenceBasis = EvidenceBasis.NONE
    state: CertificationState = CertificationState.UNRESOLVED
    valid_from: str | None = None
    valid_to: str | None = None

    def __post_init__(self) -> None:
        if not self.entity_id:
            raise ValueError("entity_id is required")
        if not self.role:
            raise ValueError("role is required")
        if not self.source_manifestation_id:
            raise ValueError("source_manifestation_id is required")
        _validate_interval(self.valid_from, self.valid_to)


@dataclass(frozen=True)
class RelationshipAssertion:
    """Typed non-monetary edge assertion with provenance and validity."""

    assertion_id: str
    subject_ref: str
    relation_type: str
    object_ref: str
    family: RelationshipFamily
    source_manifestation_id: str
    evidence_basis: EvidenceBasis = EvidenceBasis.NONE
    state: CertificationState = CertificationState.UNRESOLVED
    valid_from: str | None = None
    valid_to: str | None = None

    def __post_init__(self) -> None:
        if not self.assertion_id:
            raise ValueError("assertion_id is required")
        if not self.subject_ref or not self.object_ref:
            raise ValueError("relationship endpoints are required")
        if self.subject_ref == self.object_ref:
            raise ValueError("self relationships are not permitted")
        if not self.relation_type:
            raise ValueError("relation_type is required")
        if not self.source_manifestation_id:
            raise ValueError("source_manifestation_id is required")
        _validate_interval(self.valid_from, self.valid_to)


@dataclass(frozen=True)
class MoneyFlowObservation:
    """Source observation of money movement; an unknown amount remains None."""

    flow_id: str
    payer_entity_id: str
    payee_entity_id: str
    flow_type: str
    source_manifestation_id: str
    amount: float | None = None
    currency: str | None = None
    observed_date: str | None = None
    period_start: str | None = None
    period_end: str | None = None
    retention_state: RetentionState = RetentionState.INDETERMINATE
    ultimate_destination_state: RetentionState = RetentionState.INDETERMINATE
    state: CertificationState = CertificationState.UNRESOLVED

    def __post_init__(self) -> None:
        if not self.flow_id:
            raise ValueError("flow_id is required")
        if not self.payer_entity_id or not self.payee_entity_id:
            raise ValueError("payer_entity_id and payee_entity_id are required")
        if not self.flow_type:
            raise ValueError("flow_type is required")
        if not self.source_manifestation_id:
            raise ValueError("source_manifestation_id is required")
        if self.amount is not None and self.amount < 0:
            raise ValueError("amount cannot be negative")
        if self.amount is not None:
            valid_currency = (
                self.currency is not None
                and len(self.currency) == 3
                and self.currency == self.currency.upper()
            )
            if not valid_currency:
                raise ValueError("known amount requires a three-letter uppercase currency")
        _validate_interval(self.period_start, self.period_end)
