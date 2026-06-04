"""
Provider adapters for OPTIONAL commercial / market-data enrichment sources.

Providers in this package:
  - Are OPTIONAL (never required for pipeline coverage gates)
  - Must skip cleanly when keys / license approvals are absent
  - Must NOT call out to networks during tests
  - Must NOT persist raw vendor payloads to disk by default

Provider interface (see MarketEnrichmentProvider) defines the minimum surface a
new commercial enrichment source must implement.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class ProviderReadiness:
    """Structured skip-or-go signal for an optional provider."""
    provider: str
    key_present: bool
    license_approved: bool
    ready_for_live: bool
    status: str           # one of: "ready", "missing_key", "missing_license", "missing_both"
    license_status: str   # "approved" | "not_approved" | "unknown"
    details: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "provider":         self.provider,
            "key_present":      self.key_present,
            "license_approved": self.license_approved,
            "ready_for_live":   self.ready_for_live,
            "status":           self.status,
            "license_status":   self.license_status,
            "details":          dict(self.details),
        }


class MarketEnrichmentProvider(Protocol):
    """Minimal interface every optional commercial enrichment provider implements."""

    provider_name: str
    category: str  # always "optional_commercial_enrichment" for this package

    def readiness(self) -> ProviderReadiness: ...

    def is_ready(self) -> bool: ...
