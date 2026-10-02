from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping


class PropositionType(str, Enum):
    IDENTIFIER_IDENTITY = "IDENTIFIER_IDENTITY"
    EVENT_IDENTITY = "EVENT_IDENTITY"
    ENTITY_IDENTITY = "ENTITY_IDENTITY"
    PROPERTY_PROJECT_IDENTITY = "PROPERTY_PROJECT_IDENTITY"
    FINANCIAL_ATTRIBUTION = "FINANCIAL_ATTRIBUTION"


class CertificationState(str, Enum):
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
    PRIMARY_INTERFACE_REQUIRED = "PRIMARY_INTERFACE_REQUIRED"
    PRIMARY_ARTIFACT_NOT_FOUND = "PRIMARY_ARTIFACT_NOT_FOUND"
    NEGATIVELY_CLOSED = "NEGATIVELY_CLOSED"
    DEMONSTRABLY_INACCESSIBLE = "DEMONSTRABLY_INACCESSIBLE"


class Cardinality(str, Enum):
    ONE_TO_ONE = "1:1"
    ONE_TO_MANY = "1:N"
    MANY_TO_ONE = "N:1"
    MANY_TO_MANY = "N:N"
    ZERO_TO_ONE = "0:1"
    UNRESOLVED = "UNRESOLVED"


class EvidenceBasis(str, Enum):
    STABLE_ID = "STABLE_ID"
    AUTHORITATIVE_BINDING = "AUTHORITATIVE_BINDING"
    CERTIFIED_GEOMETRY = "CERTIFIED_GEOMETRY"
    POINT_IN_POLYGON_WITH_ALIAS_OR_ID = "POINT_IN_POLYGON_WITH_ALIAS_OR_ID"
    POINT_IN_POLYGON = "POINT_IN_POLYGON"
    AUTHORITATIVE_ALIAS_WITH_SPATIOTEMPORAL_SUPPORT = (
        "AUTHORITATIVE_ALIAS_WITH_SPATIOTEMPORAL_SUPPORT"
    )
    HISTORICAL_CONTINUITY_WITH_CORROBORATION = "HISTORICAL_CONTINUITY_WITH_CORROBORATION"
    PROXIMITY_ONLY = "PROXIMITY_ONLY"
    HEURISTIC_DISCOVERY_ONLY = "HEURISTIC_DISCOVERY_ONLY"
    NONE = "NONE"


BINDING_BASES = {
    EvidenceBasis.STABLE_ID,
    EvidenceBasis.AUTHORITATIVE_BINDING,
    EvidenceBasis.CERTIFIED_GEOMETRY,
    EvidenceBasis.POINT_IN_POLYGON_WITH_ALIAS_OR_ID,
    EvidenceBasis.POINT_IN_POLYGON,
    EvidenceBasis.AUTHORITATIVE_ALIAS_WITH_SPATIOTEMPORAL_SUPPORT,
    EvidenceBasis.HISTORICAL_CONTINUITY_WITH_CORROBORATION,
}

FORBIDDEN_SOLE_IDENTITY_BASES = {
    "NAME_ONLY",
    "NORMALIZED_NAME_ONLY",
    "COUNT_EQUALITY",
    "NEAREST_ONLY",
    "PROXIMITY_ONLY",
    "SAME_CATEGORY",
    "SOURCE_ABSENCE",
}


@dataclass(frozen=True)
class SourceManifestation:
    manifestation_id: str
    source_namespace: str
    source_record_id: str
    raw_name: str | None = None
    raw_value: str | None = None
    normalized_value: str | None = None
    canonical_value: str | None = None
    source_epoch: str | None = None
    stable_ids: Mapping[str, str] = field(default_factory=dict)
    attributes: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Proposition:
    proposition_id: str
    proposition_type: PropositionType
    subject_ref: str
    predicate: str
    object_ref: str
    cardinality: Cardinality = Cardinality.UNRESOLVED
    state: CertificationState = CertificationState.UNRESOLVED
    evidence_basis: EvidenceBasis = EvidenceBasis.NONE
    positive_evidence: tuple[str, ...] = ()
    negative_evidence: tuple[str, ...] = ()
    contradictions: tuple[str, ...] = ()
    supersedes: tuple[str, ...] = ()


@dataclass(frozen=True)
class NamespaceBinding:
    namespace: str
    identifier: str
    subject_ref: str
    source_manifestation_id: str


@dataclass(frozen=True)
class FinancialAmount:
    value: float
    semantics: str
    currency: str | None = None


@dataclass(frozen=True)
class DependencyState:
    dependency_id: str
    state: CertificationState
    prerequisites: tuple[str, ...] = ()
    reason: str = ""
