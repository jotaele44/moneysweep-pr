from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .resolution_core import Candidate, EvidenceBasis, resolve_candidates


_LEGACY_BASIS_MAP = {
    "STABLE_ID": EvidenceBasis.STABLE_ID,
    "AUTHORITATIVE_BINDING": EvidenceBasis.AUTHORITATIVE_BINDING,
    "AUTHORITATIVE_ALIAS_WITH_CORROBORATION": EvidenceBasis.AUTHORITATIVE_ALIAS_WITH_SPATIOTEMPORAL_SUPPORT,
    "HISTORICAL_CONTINUITY_WITH_CORROBORATION": EvidenceBasis.HISTORICAL_CONTINUITY_WITH_CORROBORATION,
    "HEURISTIC_DISCOVERY_ONLY": EvidenceBasis.HEURISTIC_DISCOVERY_ONLY,
    "NONE": EvidenceBasis.NONE,
}


@dataclass(frozen=True)
class IdentityCandidate:
    candidate_id: str
    binding_basis: str
    evidence_value: str


@dataclass(frozen=True)
class IdentityResolution:
    status: str
    selected_id: str | None
    candidates: tuple[IdentityCandidate, ...]
    reason: str


def resolve_identity_candidates(candidates: Iterable[IdentityCandidate]) -> IdentityResolution:
    """Compatibility wrapper over the canonical resolution_core identity engine."""
    preserved = tuple(candidates)
    core_candidates = [
        Candidate(
            candidate_id=candidate.candidate_id,
            basis=_LEGACY_BASIS_MAP.get(candidate.binding_basis, EvidenceBasis.NONE),
            evidence_ref=candidate.evidence_value,
        )
        for candidate in preserved
    ]
    result = resolve_candidates(core_candidates)
    return IdentityResolution(
        status=result.state.value,
        selected_id=result.selected_id,
        candidates=preserved,
        reason=result.reason,
    )
