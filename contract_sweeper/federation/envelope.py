"""Shared evidence envelope — Contract-Sweeper producer copy.

This is an independent copy of the cross-repo federation contract. It is
intentionally NOT shared via import with the other producer: each repo owns
its own copy so the producers stay decoupled and independently testable.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# The canonical field set of the shared evidence envelope.
ENVELOPE_FIELDS = (
    "producer",
    "record_type",
    "record_id",
    "source_id",
    "timestamp",
    "geo",
    "entities",
    "confidence",
    "lineage",
    "payload",
    "synthetic",
)

_DEFAULT_CONFIDENCE = {"score": 0.0, "method": "producer_contract"}


@dataclass
class EvidenceEnvelope:
    """One normalized record in a federation export stream."""

    producer: str
    record_type: str
    record_id: str
    source_id: str
    timestamp: Optional[str] = None
    geo: Optional[Dict[str, Any]] = None
    entities: List[Dict[str, Any]] = field(default_factory=list)
    confidence: Dict[str, Any] = field(default_factory=lambda: dict(_DEFAULT_CONFIDENCE))
    lineage: List[Any] = field(default_factory=list)
    payload: Dict[str, Any] = field(default_factory=dict)
    synthetic: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "producer": self.producer,
            "record_type": self.record_type,
            "record_id": self.record_id,
            "source_id": self.source_id,
            "timestamp": self.timestamp,
            "geo": self.geo,
            "entities": list(self.entities),
            "confidence": dict(self.confidence),
            "lineage": list(self.lineage),
            "payload": dict(self.payload),
            "synthetic": bool(self.synthetic),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "EvidenceEnvelope":
        missing = [k for k in ("producer", "record_type", "record_id", "source_id") if k not in d]
        if missing:
            raise ValueError(f"envelope missing required keys: {missing}")
        return cls(
            producer=d["producer"],
            record_type=d["record_type"],
            record_id=d["record_id"],
            source_id=d["source_id"],
            timestamp=d.get("timestamp"),
            geo=d.get("geo"),
            entities=list(d.get("entities") or []),
            confidence=dict(d.get("confidence") or _DEFAULT_CONFIDENCE),
            lineage=list(d.get("lineage") or []),
            payload=dict(d.get("payload") or {}),
            synthetic=bool(d.get("synthetic", False)),
        )


def entity_ref(entity_id: str, name: str, normalized_name: str) -> Dict[str, str]:
    """Build an `entities[]` member with the three required keys."""
    return {"entity_id": entity_id, "name": name, "normalized_name": normalized_name}
