from __future__ import annotations

from dataclasses import dataclass

from .models import CertificationState


CONTRADICTION_CLASSES = {
    "BYTE",
    "SCHEMA",
    "GEOMETRY",
    "NAME",
    "COUNT",
    "CLASS",
    "IDENTITY",
    "TIME",
    "SCOPE",
    "ADDRESS",
    "SOURCE_MANIFESTATION",
}


@dataclass(frozen=True)
class Contradiction:
    contradiction_id: str
    contradiction_class: str
    observations: tuple[str, ...]
    state: CertificationState = CertificationState.OPEN
    controlling_observation: str | None = None
    superseded_observations: tuple[str, ...] = ()
    reason: str = ""


def adjudicate_contradiction(
    contradiction: Contradiction,
    *,
    controlling_observation: str,
    superseded_observations: tuple[str, ...] = (),
    reason: str,
) -> Contradiction:
    if contradiction.contradiction_class not in CONTRADICTION_CLASSES:
        raise ValueError("unsupported contradiction class")
    if controlling_observation not in contradiction.observations:
        raise ValueError("controlling observation must be preserved in contradiction observations")
    if any(item not in contradiction.observations for item in superseded_observations):
        raise ValueError("superseded observation missing from contradiction observations")
    return Contradiction(
        contradiction_id=contradiction.contradiction_id,
        contradiction_class=contradiction.contradiction_class,
        observations=contradiction.observations,
        state=CertificationState.PASS,
        controlling_observation=controlling_observation,
        superseded_observations=superseded_observations,
        reason=reason,
    )
