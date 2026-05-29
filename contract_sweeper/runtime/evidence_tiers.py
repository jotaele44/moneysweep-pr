"""Evidence tiering for Canonical Entity Relationship Model v1.

Evidence is first-class: every graph edge resolves to >=1 evidence row, and
each evidence row carries a tier ``T1``-``T4``. This module defines the tier
criteria, the default tier derivation from ``(source_type, extraction_method)``,
the confidence floor per tier, and the crosswalk to the claim tiers in
``docs/CLAIM_LANGUAGE_POLICY.md`` (Observed / Linked / Inferred / Blocked).

Stdlib only.
"""
from __future__ import annotations

TIERS = ("T1", "T2", "T3", "T4")

TIER_CRITERIA: dict[str, str] = {
    "T1": "Primary official record, directly sourced and verified (registry/filing/court docket).",
    "T2": "Official document or API, machine-parsed without manual verification.",
    "T3": "Secondary or OCR/web-extracted material requiring corroboration.",
    "T4": "Unverified, derived, or inferred material; lowest trust.",
}

# Confidence floor contributed by the tier alone (before method adjustments).
_TIER_CONFIDENCE: dict[str, float] = {"T1": 0.95, "T2": 0.85, "T3": 0.6, "T4": 0.35}

# Default tier by source_type (overridable by extraction_method below).
_SOURCE_TYPE_TIER: dict[str, str] = {
    "registry": "T1",
    "filing": "T1",
    "court_docket": "T1",
    "csv": "T2",
    "api": "T2",
    "pdf": "T2",
    "web": "T3",
    "other": "T4",
}

# Extraction methods that cap the achievable tier (cannot exceed this).
_METHOD_TIER_CAP: dict[str, str] = {
    "manual": "T1",
    "API": "T2",
    "parser": "T2",
    "OCR": "T3",
    "web": "T3",
    "other": "T4",
}

# Evidence tier -> claim tier (CLAIM_LANGUAGE_POLICY).
_CLAIM_TIER: dict[str, str] = {
    "T1": "observed",
    "T2": "observed",
    "T3": "linked",
    "T4": "inferred",
}


def _worse(a: str, b: str) -> str:
    """Return the lower-trust (numerically larger) of two tiers."""
    return a if TIERS.index(a) >= TIERS.index(b) else b


def derive_tier(source_type: str, extraction_method: str | None = None) -> str:
    """Derive an evidence tier from source type, capped by extraction method."""
    base = _SOURCE_TYPE_TIER.get((source_type or "").strip().lower(), "T4")
    if extraction_method:
        cap = _METHOD_TIER_CAP.get(extraction_method.strip(), None)
        if cap:
            base = _worse(base, cap)
    return base


def tier_confidence(tier: str) -> float:
    """Base confidence floor for a tier."""
    return _TIER_CONFIDENCE.get(tier, 0.35)


def score_evidence(tier: str, extraction_method: str | None = None,
                   ocr_confidence: float | None = None) -> float:
    """Confidence in [0,1] for an evidence row.

    Starts at the tier floor; OCR-extracted evidence multiplies by the measured
    OCR confidence so a poor scan is not over-trusted.
    """
    conf = tier_confidence(tier)
    if (extraction_method or "").strip() == "OCR" and ocr_confidence is not None:
        conf *= max(0.0, min(1.0, ocr_confidence))
    return round(max(0.0, min(1.0, conf)), 4)


def claim_tier_for(evidence_tier: str, review_status: str = "accepted") -> str:
    """Map an evidence tier + review status to a CLAIM_LANGUAGE_POLICY claim tier.

    Rejected evidence is ``blocked``; not-yet-accepted evidence is downgraded
    one trust level (worst tier wins, mirroring the maturity gate).
    """
    status = (review_status or "accepted").strip().lower()
    if status == "rejected":
        return "blocked"
    base = _CLAIM_TIER.get(evidence_tier, "inferred")
    if status != "accepted":
        downgrade = {"observed": "linked", "linked": "inferred", "inferred": "blocked"}
        return downgrade.get(base, base)
    return base
