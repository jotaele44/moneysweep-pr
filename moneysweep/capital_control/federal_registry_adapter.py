from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from typing import Any

from .resolution_core import (
    Candidate,
    CertificationState,
    EvidenceBasis,
    Resolution,
    resolve_candidates,
)

PASS_BINDING_BASES = frozenset(
    {
        EvidenceBasis.STABLE_ID.value,
        EvidenceBasis.AUTHORITATIVE_BINDING.value,
    }
)

CANDIDATE_STATE = CertificationState.CANDIDATE_NOT_IDENTITY.value
LEGACY_CANDIDATE_STATUS = "CANDIDATE_LEGACY_UNBOUND"


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def candidate_identifier(candidate: Mapping[str, Any]) -> str:
    """Return a stable discovery identifier without claiming entity identity."""
    return (
        _text(candidate.get("uei"))
        or _text(candidate.get("recipient_hash"))
        or _text(candidate.get("id"))
        or _text(candidate.get("sam_name"))
        or _text(candidate.get("name"))
        or _text(candidate.get("recipient_name"))
        or "FEDERAL_REGISTRY_CANDIDATE"
    )


def candidate_evidence_json(
    candidates: Iterable[Mapping[str, Any]],
    *,
    source: str,
    query_raw: str,
) -> str:
    """Serialize the complete bounded discovery set in source order."""
    preserved = []
    for index, candidate in enumerate(candidates):
        preserved.append(
            {
                "rank": index + 1,
                "source": source,
                "query_raw": query_raw,
                "candidate_id": candidate_identifier(candidate),
                "candidate_uei": _text(candidate.get("uei")),
                "candidate_cage": _text(candidate.get("cage")),
                "candidate_duns": _text(candidate.get("duns")),
                "candidate_name_raw": _text(
                    candidate.get("sam_name")
                    or candidate.get("name")
                    or candidate.get("recipient_name")
                ),
                "match_score": candidate.get("match_score", 0),
                "status_raw": _text(candidate.get("status")),
                "state_raw": _text(candidate.get("state")),
                "parent_uei_candidate": _text(candidate.get("parent_uei")),
                "parent_name_candidate_raw": _text(candidate.get("parent_name")),
            }
        )
    return json.dumps(preserved, ensure_ascii=False, sort_keys=True)


def adjudicate_registry_candidate(
    candidate: Mapping[str, Any],
    *,
    evidence_ref: str,
    known_uei: str = "",
    explicit_binding_basis: str = "",
) -> Resolution:
    """Route a registry candidate through the canonical resolution core.

    A name-search candidate is discovery only. It can PASS only when the caller
    supplies an independent matching UEI or an explicit authoritative binding.
    """
    candidate_uei = _text(candidate.get("uei"))
    explicit = _text(explicit_binding_basis)
    if known_uei and candidate_uei and known_uei == candidate_uei:
        basis = EvidenceBasis.STABLE_ID
    elif explicit == EvidenceBasis.AUTHORITATIVE_BINDING.value:
        basis = EvidenceBasis.AUTHORITATIVE_BINDING
    elif explicit == EvidenceBasis.STABLE_ID.value:
        basis = EvidenceBasis.STABLE_ID
    else:
        basis = EvidenceBasis.HEURISTIC_DISCOVERY_ONLY
    return resolve_candidates(
        [
            Candidate(
                candidate_id=candidate_identifier(candidate),
                basis=basis,
                evidence_ref=evidence_ref,
            )
        ]
    )


def is_certified_binding(row: Mapping[str, Any]) -> bool:
    return (
        _text(row.get("identity_state")) == CertificationState.PASS.value
        and _text(row.get("binding_basis")) in PASS_BINDING_BASES
        and bool(_text(row.get("uei")))
    )


def certified_record(
    *,
    vendor_name_raw: str,
    candidate: Mapping[str, Any],
    basis: str,
    source: str,
    resolution_status: str,
    candidate_set_json: str = "[]",
) -> dict[str, Any]:
    if basis not in PASS_BINDING_BASES:
        raise ValueError("certified federal identifier requires stable-ID or authoritative binding")
    uei = _text(candidate.get("uei"))
    if not uei:
        raise ValueError("certified federal identifier requires a nonempty UEI")
    return {
        "vendor_name_raw": vendor_name_raw,
        "uei": uei,
        "cage": _text(candidate.get("cage")),
        "duns": _text(candidate.get("duns")),
        "sam_name": _text(candidate.get("sam_name") or candidate.get("name")),
        "match_score": candidate.get("match_score", 0),
        "status": _text(candidate.get("status")),
        "expiry": _text(candidate.get("expiry")),
        "state": _text(candidate.get("state")),
        "parent_uei": _text(candidate.get("parent_uei")),
        "parent_name": _text(candidate.get("parent_name")),
        "source": source,
        "resolution_status": resolution_status,
        "identity_state": CertificationState.PASS.value,
        "binding_basis": basis,
        "candidate_uei": "",
        "candidate_cage": "",
        "candidate_duns": "",
        "candidate_name": "",
        "candidate_source": "",
        "candidate_set_json": candidate_set_json,
    }


def candidate_record(
    *,
    vendor_name_raw: str,
    candidate: Mapping[str, Any],
    source: str,
    resolution_status: str,
    candidate_set_json: str,
) -> dict[str, Any]:
    """Preserve a discovery candidate without placing IDs in certified fields."""
    return {
        "vendor_name_raw": vendor_name_raw,
        "uei": "",
        "cage": "",
        "duns": "",
        "sam_name": "",
        "match_score": candidate.get("match_score", 0),
        "status": "CANDIDATE",
        "expiry": "",
        "state": "",
        "parent_uei": "",
        "parent_name": "",
        "source": source,
        "resolution_status": resolution_status,
        "identity_state": CANDIDATE_STATE,
        "binding_basis": EvidenceBasis.HEURISTIC_DISCOVERY_ONLY.value,
        "candidate_uei": _text(candidate.get("uei")),
        "candidate_cage": _text(candidate.get("cage")),
        "candidate_duns": _text(candidate.get("duns")),
        "candidate_name": _text(
            candidate.get("sam_name") or candidate.get("name") or candidate.get("recipient_name")
        ),
        "candidate_source": source,
        "candidate_set_json": candidate_set_json,
    }


def sanitize_legacy_record(row: Mapping[str, Any]) -> dict[str, Any]:
    """Fail closed on legacy rows that carried IDs without binding metadata."""
    sanitized = dict(row)
    if is_certified_binding(sanitized):
        return sanitized

    resolution_status = _text(sanitized.get("resolution_status"))
    uei = _text(sanitized.get("uei"))
    if resolution_status == "RESOLVED_SOURCE_UEI" and uei:
        sanitized["identity_state"] = CertificationState.PASS.value
        sanitized["binding_basis"] = EvidenceBasis.STABLE_ID.value
        sanitized.setdefault("vendor_name_raw", _text(sanitized.get("vendor_name")))
        return sanitized

    if uei:
        sanitized["candidate_uei"] = _text(sanitized.get("candidate_uei")) or uei
        sanitized["candidate_cage"] = _text(sanitized.get("candidate_cage")) or _text(
            sanitized.get("cage")
        )
        sanitized["candidate_duns"] = _text(sanitized.get("candidate_duns")) or _text(
            sanitized.get("duns")
        )
        sanitized["candidate_name"] = _text(sanitized.get("candidate_name")) or _text(
            sanitized.get("sam_name")
        )
        sanitized["candidate_source"] = _text(sanitized.get("candidate_source")) or _text(
            sanitized.get("source")
        )
        sanitized["uei"] = ""
        sanitized["cage"] = ""
        sanitized["duns"] = ""
        sanitized["sam_name"] = ""
        sanitized["parent_uei"] = ""
        sanitized["parent_name"] = ""
        sanitized["identity_state"] = CANDIDATE_STATE
        sanitized["binding_basis"] = EvidenceBasis.HEURISTIC_DISCOVERY_ONLY.value
        sanitized["resolution_status"] = LEGACY_CANDIDATE_STATUS
    else:
        sanitized.setdefault("identity_state", CertificationState.UNRESOLVED.value)
        sanitized.setdefault("binding_basis", EvidenceBasis.NONE.value)
    sanitized.setdefault("candidate_set_json", "[]")
    sanitized.setdefault("vendor_name_raw", _text(sanitized.get("vendor_name")))
    return sanitized
