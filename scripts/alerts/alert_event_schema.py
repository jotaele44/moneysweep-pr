"""Schemas for project-emergence alert events."""

from __future__ import annotations

import sys
from dataclasses import asdict, dataclass, field
from enum import IntEnum
from typing import Any

if sys.version_info >= (3, 11):
    from enum import StrEnum
else:  # pragma: no cover - Python 3.10 has no enum.StrEnum
    from enum import Enum

    class StrEnum(str, Enum):
        """Minimal backport of enum.StrEnum for Python 3.10."""

        def __str__(self) -> str:
            return str(self.value)


class AlertLevel(StrEnum):
    BACKGROUND = "background"
    WATCH = "watch"
    REVIEW = "review"
    URGENT = "urgent"
    CRITICAL = "critical"


class ProjectStage(IntEnum):
    RUMOR_MEDIA_ONLY = 0
    ENTITY_FORMATION = 1
    PLANNING_VISIBILITY = 2
    FUNDING_VISIBILITY = 3
    PROFESSIONAL_SERVICES = 4
    INFRASTRUCTURE_PREPARATION = 5
    CONSTRUCTION_PROCUREMENT = 6
    OPERATIONS_LAYER = 7
    EXPANSION_AMENDMENT = 8


@dataclass(slots=True)
class AlertEvent:
    alert_id: str
    project_id: str
    canonical_name: str
    alert_level: str
    score: int
    trigger_reason: list[str]
    source: str = ""
    source_family: str = ""
    record_id: str = ""
    record_date: str = ""
    agency: str = ""
    vendor: str = ""
    amount: float | None = None
    municipio: str = ""
    parcel_id: str = ""
    project_stage: int = 0
    confidence: float = 0.0
    requires_spiderweb: bool = False
    dedupe_key: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
