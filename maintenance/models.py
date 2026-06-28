"""Dataclasses + vocabulary for maintenance findings/reports.

Field-for-field compatible with the Hub's maintenance_finding/report schemas.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

MAINTENANCE_VERSION = "0.1.0"

CATEGORIES = (
    "manifest",
    "schema",
    "export_integrity",
    "source_staleness",
    "lineage",
    "duplicate",
    "contradiction",
    "synthetic_leakage",
    "artifact_hygiene",
    "test_gap",
    "dependency_drift",
    "promotion_gate",
)
SEVERITIES = ("info", "warning", "error", "critical")
ACTIONS = ("none", "auto_corrected", "quarantined", "blocked")


@dataclass
class MaintenanceFinding:
    finding_id: str
    repo: str
    category: str
    severity: str
    action: str = "none"
    confidence: float = 1.0
    message: str = ""
    path: str | None = None
    detail: dict | None = None

    def to_dict(self) -> dict:
        out: dict = {
            "finding_id": self.finding_id,
            "repo": self.repo,
            "category": self.category,
            "severity": self.severity,
            "action": self.action,
            "confidence": self.confidence,
        }
        if self.message:
            out["message"] = self.message
        if self.path is not None:
            out["path"] = self.path
        if self.detail is not None:
            out["detail"] = self.detail
        return out


@dataclass
class MaintenanceReport:
    repo: str
    findings: list[MaintenanceFinding] = field(default_factory=list)
    mode: str = "audit"
    maintenance_version: str = MAINTENANCE_VERSION

    @property
    def critical_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "critical")

    @property
    def promotion_blocked(self) -> bool:
        return any(f.severity == "critical" or f.action == "blocked" for f in self.findings)

    def to_dict(self) -> dict:
        return {
            "repo": self.repo,
            "maintenance_version": self.maintenance_version,
            "mode": self.mode,
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "findings_count": len(self.findings),
            "critical_count": self.critical_count,
            "promotion_blocked": self.promotion_blocked,
            "findings": [f.to_dict() for f in self.findings],
        }
