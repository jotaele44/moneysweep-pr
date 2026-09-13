from __future__ import annotations

from dataclasses import dataclass

from .gates import evaluate_foia_gate, federation_unlock, funding_unlock, parcel_unlock
from .models import (
    Cardinality,
    CertificationState,
    EvidenceBasis,
    Proposition,
    PropositionType,
)
from .namespace import NamespaceRegistry


@dataclass
class ResolutionCore:
    namespaces: NamespaceRegistry

    @classmethod
    def create(cls) -> "ResolutionCore":
        return cls(NamespaceRegistry())

    def dependency_states(
        self, states: dict[str, CertificationState]
    ) -> dict[str, CertificationState]:
        source_states = {
            key.removeprefix("source:"): value
            for key, value in states.items()
            if key.startswith("source:")
        }
        return {
            "parcel": parcel_unlock(states).state,
            "federation": federation_unlock(states).state,
            "funding": funding_unlock(states).state,
            "foia": evaluate_foia_gate(source_states).state,
        }


def make_proposition(
    proposition_id: str,
    proposition_type: PropositionType,
    subject_ref: str,
    predicate: str,
    object_ref: str,
    *,
    cardinality: Cardinality = Cardinality.UNRESOLVED,
    state: CertificationState = CertificationState.UNRESOLVED,
    evidence_basis: EvidenceBasis = EvidenceBasis.NONE,
) -> Proposition:
    return Proposition(
        proposition_id=proposition_id,
        proposition_type=proposition_type,
        subject_ref=subject_ref,
        predicate=predicate,
        object_ref=object_ref,
        cardinality=cardinality,
        state=state,
        evidence_basis=evidence_basis,
    )
