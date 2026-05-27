"""Entity-mode query types.

Parallel to :mod:`contract_sweeper.query.types`: where ``Query`` is keyed on
PR geography, :class:`EntityQuery` is keyed on entity identifiers
(UEI / CAGE / DUNS / name / EIN / CIK). Sources whose upstream APIs are
shaped around entity lookup (SAM, OFAC SDN, SEC EDGAR) consume this type.

The dispatcher and cache machinery treat :class:`EntityQuery` and
:class:`Query` interchangeably for hashing, but they ride separate adapter
registries so callers can't accidentally route a geographic source through
an entity-mode call (or vice-versa).
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Literal

EntityKind = Literal["uei", "name", "cage", "duns", "ein", "cik"]
SUPPORTED_KINDS: frozenset[str] = frozenset({"uei", "name", "cage", "duns", "ein", "cik"})


@dataclass(frozen=True)
class EntityIdentifier:
    """A single typed entity identifier (e.g. ``uei=QY9NQNTZSF89``)."""

    kind: EntityKind
    value: str

    def __post_init__(self) -> None:
        if self.kind not in SUPPORTED_KINDS:
            raise ValueError(f"unsupported entity kind: {self.kind!r}")
        if not self.value or not str(self.value).strip():
            raise ValueError("entity identifier value must be non-empty")

    def canonical(self) -> tuple[str, str]:
        return (self.kind, str(self.value).strip())


@dataclass(frozen=True)
class EntityQuery:
    """Entity-mode query: a list of typed identifiers to look up.

    Identifier order doesn't affect the cache hash — the canonical form
    sorts by ``(kind, value)`` and dedups exact matches.
    """

    identifiers: tuple[EntityIdentifier, ...] = field(default_factory=tuple)

    def canonical_dict(self) -> dict[str, Any]:
        seen = {ident.canonical() for ident in self.identifiers}
        return {
            "identifiers": [
                {"kind": k, "value": v} for (k, v) in sorted(seen)
            ],
        }

    def canonical_hash(self) -> str:
        payload = json.dumps(self.canonical_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]

    def by_kind(self, *kinds: str) -> list[str]:
        """Return all identifier values whose kind is in ``kinds`` (deduped, sorted)."""
        wanted = set(kinds)
        return sorted({
            str(ident.value).strip()
            for ident in self.identifiers
            if ident.kind in wanted
        })
