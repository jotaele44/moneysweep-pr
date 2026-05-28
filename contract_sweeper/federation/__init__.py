"""Cross-repo federation producer contract for Contract-Sweeper.

Emits a validated export package (manifest + JSONL streams) shaped to the
shared evidence envelope, with namespaced IDs, guarded by a fail-closed
validator. This is the funding/entity/relationship producer side of the
federation. The repo does NOT import the other producer's code; the two
producers communicate only through validated export packages on disk.
"""
from __future__ import annotations

from .envelope import EvidenceEnvelope, entity_ref
from .namespace import PREFIX, PRODUCER, is_namespaced, namespaced_id
from .validator import validate_envelope, validate_financial, validate_package

__all__ = [
    "EvidenceEnvelope",
    "entity_ref",
    "PREFIX",
    "PRODUCER",
    "is_namespaced",
    "namespaced_id",
    "validate_envelope",
    "validate_financial",
    "validate_package",
]
