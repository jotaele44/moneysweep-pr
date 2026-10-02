from __future__ import annotations

from dataclasses import dataclass

from .models import BINDING_BASES, CertificationState, EvidenceBasis


EVIDENCE_PRIORITY = {
    EvidenceBasis.STABLE_ID: 900,
    EvidenceBasis.AUTHORITATIVE_BINDING: 800,
    EvidenceBasis.CERTIFIED_GEOMETRY: 700,
    EvidenceBasis.POINT_IN_POLYGON_WITH_ALIAS_OR_ID: 650,
    EvidenceBasis.POINT_IN_POLYGON: 600,
    EvidenceBasis.AUTHORITATIVE_ALIAS_WITH_SPATIOTEMPORAL_SUPPORT: 500,
    EvidenceBasis.HISTORICAL_CONTINUITY_WITH_CORROBORATION: 400,
    EvidenceBasis.PROXIMITY_ONLY: 100,
    EvidenceBasis.HEURISTIC_DISCOVERY_ONLY: 50,
    EvidenceBasis.NONE: 0,
}


@dataclass(frozen=True)
class Candidate:
    candidate_id: str
    basis: EvidenceBasis
    evidence_ref: str


@dataclass(frozen=True)
class Resolution:
    state: CertificationState
    selected_id: str | None
    candidates: tuple[Candidate, ...]
    reason: str


def resolve_candidates(candidates: tuple[Candidate, ...] | list[Candidate]) -> Resolution:
    preserved = tuple(candidates)
    if not preserved:
        return Resolution(CertificationState.UNRESOLVED, None, preserved, "no candidates")

    best = max(EVIDENCE_PRIORITY.get(candidate.basis, -1) for candidate in preserved)
    top = tuple(
        candidate for candidate in preserved if EVIDENCE_PRIORITY.get(candidate.basis, -1) == best
    )
    distinct_ids = {candidate.candidate_id for candidate in top}
    if len(distinct_ids) != 1:
        return Resolution(
            CertificationState.UNRESOLVED,
            None,
            preserved,
            "tied top evidence",
        )

    selected = top[0]
    if selected.basis not in BINDING_BASES:
        return Resolution(
            CertificationState.CANDIDATE_NOT_IDENTITY,
            None,
            preserved,
            "best evidence is non-binding",
        )
    return Resolution(
        CertificationState.PASS,
        selected.candidate_id,
        preserved,
        "binding evidence selected",
    )
