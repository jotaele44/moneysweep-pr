"""Canonical contracts schema constants and normalization helpers."""

from __future__ import annotations

from hashlib import sha1
import re
from typing import Any

CANONICAL_CONTRACT_FIELDS = [
    "entity_id",
    "parent_uei",
    "normalized_name",
    "award_id",
    "funding_source",
    "obligation_amount",
    "geo_location",
    "project_id",
    "agency",
    "source_system",
    "source_url",
    "source_date",
    "link_confidence",
    "risk_score",
]

OPTIONAL_CANONICAL_FIELDS = [
    "municipality",
    "contract_type",
    "award_status",
]

_FIELD_ALIASES = {
    "entity_name": [
        "normalized_name",
        "recipient_name",
        "vendor_name",
        "sub-awardee name",
        "sub_awardee_name",
        "prime recipient name",
        "prime_recipient_name",
    ],
    "entity_uei": [
        "recipient_uei",
        "uei",
        "parent_uei",
        "entity_uei",
    ],
    "parent_uei": [
        "parent_uei",
    ],
    "award_id": [
        "award_id",
        "contract_id",
        "piid",
        "sub-award id",
        "sub_award_id",
        "prime award id",
        "prime_award_id",
    ],
    "project_id": [
        "project_id",
        "fema_project_id",
        "project_number",
        "projectworksheetid",
        "project_worksheet_id",
    ],
    "funding_source": [
        "source_dataset",
        "award_category",
        "funding_source",
        "program",
    ],
    "obligation_amount": [
        "obligated_amount",
        "obligation_amount",
        "award_amount",
        "sub-award amount",
        "sub_award_amount",
        "projectamount",
        "federalshareobligated",
    ],
    "agency": [
        "agency",
        "awarding_agency",
        "agency_name",
        "awarding_sub_agency",
    ],
    "source_url": [
        "source_url",
        "url",
        "record_url",
    ],
    "source_date": [
        "source_date",
        "award_date",
        "filing_date",
        "sub-award date",
        "sub_award_date",
    ],
    "pop_state": [
        "pop_state",
        "place of performance state code",
        "place_of_performance_state_code",
        "state",
    ],
    "pop_county": [
        "pop_county",
        "county",
        "place_of_performance_county",
    ],
    "municipality": [
        "municipality",
        "city",
        "place_of_performance_city",
    ],
    "award_status": [
        "award_status",
        "status",
    ],
    "contract_type": [
        "contract_type",
        "award_category",
        "assistance_type_description",
    ],
}

_SPACE_RE = re.compile(r"\s+")
_STRIP_RE = re.compile(r"[^A-Z0-9 ]")


def normalize_key(value: str) -> str:
    """Normalize a key for robust alias matching."""

    lowered = value.strip().lower().replace("-", "_")
    lowered = lowered.replace(" ", "_")
    return lowered


def extract_alias(row: dict[str, Any], alias_group: str) -> str:
    """Extract the first non-empty value using alias lookup for a semantic field."""

    alias_candidates = _FIELD_ALIASES.get(alias_group, [])
    if not alias_candidates:
        return ""

    row_map = {normalize_key(key): value for key, value in row.items()}
    for alias in alias_candidates:
        value = row_map.get(normalize_key(alias))
        if value is None:
            continue
        rendered = str(value).strip()
        if rendered != "":
            return rendered
    return ""


def normalize_name(value: str) -> str:
    """Normalize entity names to a stable uppercase token string."""

    if not value:
        return ""
    normalized = str(value).upper().strip()
    normalized = _STRIP_RE.sub(" ", normalized)
    normalized = _SPACE_RE.sub(" ", normalized)
    return normalized.strip()


def parse_amount(value: str) -> float:
    """Parse numeric amount text into float with safe fallback."""

    if not value:
        return 0.0
    cleaned = str(value).strip()
    cleaned = cleaned.replace(",", "")
    cleaned = cleaned.replace("$", "")
    cleaned = cleaned.replace("(", "-").replace(")", "")
    cleaned = re.sub(r"[^0-9.\-]", "", cleaned)
    if cleaned in {"", "-", ".", "-."}:
        return 0.0
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def format_geo_location(pop_state: str, pop_county: str, municipality: str) -> str:
    """Render normalized location string."""

    parts = [p.strip() for p in [municipality, pop_county, pop_state] if str(p).strip()]
    return ", ".join(parts)


def derive_entity_id(normalized_name_value: str, entity_uei: str, source_system: str) -> str:
    """Derive stable entity_id. Prefer UEI when available."""

    if entity_uei:
        return entity_uei.strip()
    seed = f"{source_system}|{normalized_name_value}".encode("utf-8")
    digest = sha1(seed).hexdigest()[:16]
    return f"anon-{digest}"
