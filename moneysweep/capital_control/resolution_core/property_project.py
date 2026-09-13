from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .models import CertificationState, EvidenceBasis


class SpatialState(str, Enum):
    FULLY_WITHIN = "FULLY_WITHIN"
    PARTIAL = "PARTIAL"
    TOUCH_ONLY = "TOUCH_ONLY"
    OUTSIDE = "OUTSIDE"
    NULL_EMPTY = "NULL_EMPTY"
    UNRESOLVED = "UNRESOLVED"


@dataclass(frozen=True)
class PropertyProjectBinding:
    state: CertificationState
    project_ref: str | None
    property_ref: str | None
    spatial_state: SpatialState
    reason: str


def bind_property_project(
    *,
    project_ref: str | None,
    property_ref: str | None,
    authoritative_property_anchor: bool,
    evidence_basis: EvidenceBasis,
    spatial_state: SpatialState = SpatialState.UNRESOLVED,
) -> PropertyProjectBinding:
    if not authoritative_property_anchor or not property_ref:
        return PropertyProjectBinding(
            CertificationState.BLOCKED,
            project_ref,
            property_ref,
            SpatialState.UNRESOLVED,
            "authoritative property anchor required before parcel identity",
        )
    if evidence_basis in {
        EvidenceBasis.PROXIMITY_ONLY,
        EvidenceBasis.HEURISTIC_DISCOVERY_ONLY,
        EvidenceBasis.NONE,
    }:
        return PropertyProjectBinding(
            CertificationState.CANDIDATE_NOT_IDENTITY,
            project_ref,
            property_ref,
            spatial_state,
            "non-binding discovery evidence cannot certify property identity",
        )
    return PropertyProjectBinding(
        CertificationState.PASS,
        project_ref,
        property_ref,
        spatial_state,
        "authoritative property binding accepted",
    )
