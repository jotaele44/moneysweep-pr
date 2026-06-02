"""Deterministic ID generation for Canonical Entity Relationship Model v1.

No random UUIDs for core nodes — IDs are pure functions of their identifying
payload, so the same real-world thing yields the same ID across runs and
sources. Patterns follow ``docs/canonical_entity_relationship_model_v1.md``:

==================  ===========================================
Node                Pattern
==================  ===========================================
Person              ``person_<normalized_name_hash>``
Entity              ``entity_<normalized_name_hash>``
Contract            ``contract_<agency>_<contract_number>``
Project             ``project_<source>_<project_number>``
Debt                ``debt_<issuer>_<class>_<year>``
Lobbying            ``lobby_<jurisdiction>_<registration>_<quarter>``
Funding             ``funding_<program>_<year>``
Municipality        ``muni_pr_<normalized_name>``
Edge                ``edge_<hash(source|type|target)>``
Evidence            ``evidence_<source>_<ref>_<hash>``
==================  ===========================================

All generated IDs match ``^<prefix>_[A-Za-z0-9_]+$`` (the canonical_v1
schema patterns). Stdlib only.
"""
from __future__ import annotations

import hashlib
import re

from contract_sweeper.runtime.name_normalization import (
    normalize_name,
    normalize_person_name,
)

_SLUG_STRIP = re.compile(r"[^a-z0-9]+")
_NAME_HASH_LEN = 16
_EDGE_HASH_LEN = 24
_EVIDENCE_HASH_LEN = 10


def _hash(text: str, length: int) -> str:
    """Stable lowercase-hex sha256 prefix of ``text``."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:length]


def slug(value: str | None, *, default: str = "na") -> str:
    """Lowercase, underscore-joined, alphanumeric token suitable for an ID part."""
    if not value:
        return default
    s = _SLUG_STRIP.sub("_", str(value).strip().lower()).strip("_")
    return s or default


def name_hash(name: str | None, *, person: bool = False) -> str:
    """Deterministic hash of a normalized name (org by default, person if set)."""
    normalized = normalize_person_name(name) if person else normalize_name(name)
    return _hash(normalized, _NAME_HASH_LEN)


# --------------------------------------------------------------------------- #
# Node IDs
# --------------------------------------------------------------------------- #

def person_id(full_name: str | None) -> str:
    return f"person_{name_hash(full_name, person=True)}"


def entity_id(name: str | None) -> str:
    return f"entity_{name_hash(name)}"


def contract_id(agency: str | None, contract_number: str | None) -> str:
    return f"contract_{slug(agency)}_{slug(contract_number)}"


def project_id(source: str | None, project_number: str | None) -> str:
    return f"project_{slug(source)}_{slug(project_number)}"


def debt_id(issuer: str | None, debt_class: str | None, year: str | int | None) -> str:
    return f"debt_{slug(issuer)}_{slug(debt_class)}_{slug(str(year) if year is not None else None)}"


def lobbying_id(jurisdiction: str | None, registration: str | None, quarter: str | None) -> str:
    return f"lobby_{slug(jurisdiction)}_{slug(registration)}_{slug(quarter)}"


def funding_id(program: str | None, year: str | int | None) -> str:
    return f"funding_{slug(program)}_{slug(str(year) if year is not None else None)}"


def municipality_id(name: str | None) -> str:
    return f"muni_pr_{slug(normalize_name(name))}"


def property_id(name: str | None, owner: str | None = None) -> str:
    """Deterministic id for a property/asset from its owner + name."""
    return f"property_{slug(owner)}_{slug(name)}"


# --------------------------------------------------------------------------- #
# Edge / evidence IDs
# --------------------------------------------------------------------------- #

def edge_id(source_node_id: str | None, edge_type: str | None, target_node_id: str | None) -> str:
    """Stable edge id from the (source, verb, target) triple."""
    payload = f"{source_node_id or ''}|{edge_type or ''}|{target_node_id or ''}"
    return f"edge_{_hash(payload, _EDGE_HASH_LEN)}"


def evidence_id(source: str | None, ref: str | None, payload: str | None = None) -> str:
    """Stable evidence id from source + row/page ref (+ optional claim payload)."""
    digest_input = f"{source or ''}|{ref or ''}|{payload or ''}"
    return f"evidence_{slug(source)}_{slug(ref)}_{_hash(digest_input, _EVIDENCE_HASH_LEN)}"
