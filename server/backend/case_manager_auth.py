"""Verified identity for the Case Manager service boundary.

Before this module, ``case_manager_api`` derived both the acting identity and
the read clearance straight from client-supplied headers::

    def _actor(value):     return value or "anonymous"
    def _clearance(value): return value or "public"

which meant any caller could write audit history under any name, and could read
restricted records by sending ``X-Case-Clearance: restricted`` -- the header set
the caller's rank in ``VISIBILITY_RANK`` directly. Absent headers still
authorized. See finding D4 in docs/GAP_ANALYSIS_AND_OPTIMIZATION_2026-09.md.

Here, actor and clearance are *derived from a verified credential* and are no
longer readable from the request at all. This is the interim step
docs/BACKEND_ASSESSMENT_AND_DEVELOPMENT_PLAN.md calls for, ahead of the
federation-wide identity provider; it is deliberately small and stdlib-only so
that provider can replace it without unwinding anything.

Credential storage: the identity file holds **SHA-256 hashes only, never raw
tokens**, so the file at rest contains no usable credential
(docs/SECRET_HANDLING_POLICY.md). A presented token is hashed and compared with
``secrets.compare_digest``.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import HTTPException, Request

from moneysweep.case_manager.service import VISIBILITY_RANK
from server.backend.local_request import require_loopback

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_IDENTITIES_PATH = ROOT / "data" / "case_manager_identities.json"
TOKEN_HEADER = "X-Case-Token"


@dataclass(frozen=True)
class Identity:
    """A caller proven by credential. Never constructed from request headers."""

    actor: str
    clearance: str


# Test/or-operator hook, mirroring case_manager_api.configure_repository.
_identities: dict[str, Identity] | None = None


def _identities_path() -> Path:
    override = os.environ.get("MONEYSWEEP_CASE_IDENTITIES")
    return Path(override) if override else DEFAULT_IDENTITIES_PATH


def _parse_identities(raw: Any, source: str) -> dict[str, Identity]:
    if not isinstance(raw, list):
        raise ValueError(f"{source}: expected a JSON list of identity entries")
    table: dict[str, Identity] = {}
    for index, entry in enumerate(raw):
        if not isinstance(entry, dict):
            raise ValueError(f"{source}: entry {index} is not an object")
        digest = entry.get("token_sha256")
        actor = entry.get("actor")
        clearance = entry.get("clearance")
        if not isinstance(digest, str) or not digest:
            raise ValueError(f"{source}: entry {index} has no token_sha256")
        if not isinstance(actor, str) or not actor:
            raise ValueError(f"{source}: entry {index} has no actor")
        if clearance not in VISIBILITY_RANK:
            raise ValueError(
                f"{source}: entry {index} clearance must be one of "
                f"{sorted(VISIBILITY_RANK)}, got {clearance!r}"
            )
        table[digest.strip().lower()] = Identity(actor=actor, clearance=clearance)
    return table


def load_identities() -> dict[str, Identity]:
    """Read the identity table, or raise 503 if it is missing or malformed.

    Failing closed is the point: an unconfigured deployment must refuse
    requests, never silently fall back to the permissive pre-D4 behavior.
    """
    if _identities is not None:
        return _identities
    path = _identities_path()
    if not path.is_file():
        raise HTTPException(
            status_code=503,
            detail=(
                "case-manager identity store is not configured; set "
                "MONEYSWEEP_CASE_IDENTITIES to a JSON file of "
                "{token_sha256, actor, clearance} entries"
            ),
        )
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return _parse_identities(raw, "case-manager identity store")
    except HTTPException:
        raise
    except (OSError, ValueError) as exc:
        # Never echo the file contents -- it is credential-adjacent material.
        raise HTTPException(
            status_code=503, detail=f"case-manager identity store is unreadable: {exc}"
        ) from exc


def configure_identities(identities: dict[str, Identity] | None) -> None:
    """Test hook; production callers use the configured identity file."""
    global _identities
    _identities = identities


def token_digest(token: str) -> str:
    """Hash a raw token for storage in the identity file."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def resolve_identity(request: Request) -> Identity:
    """FastAPI dependency: the verified caller, or an HTTP error.

    403 non-loopback · 503 unconfigured · 401 missing or unknown token.
    """
    require_loopback(request, detail="case-manager access requires loopback")
    table = load_identities()
    presented = request.headers.get(TOKEN_HEADER)
    if not presented:
        raise HTTPException(status_code=401, detail=f"{TOKEN_HEADER} is required")
    candidate = token_digest(presented.strip())
    for digest, identity in table.items():
        # compare_digest on every entry: constant-time, and no early exit that
        # would leak which prefix matched.
        if secrets.compare_digest(candidate, digest):
            return identity
    raise HTTPException(status_code=401, detail="unrecognized case-manager token")
