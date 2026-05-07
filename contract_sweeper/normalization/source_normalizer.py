"""Source-level normalizer to canonical contracts schema."""

from __future__ import annotations

from typing import Any

from .canonical_contracts import (
    CANONICAL_CONTRACT_FIELDS,
    OPTIONAL_CANONICAL_FIELDS,
    derive_entity_id,
    extract_alias,
    format_geo_location,
    normalize_name,
    parse_amount,
)


class SourceContractsNormalizer:
    """Normalize source records into canonical contracts rows."""

    def __init__(self, source_id: str) -> None:
        self.source_id = source_id

    def normalize_row(self, row: dict[str, Any]) -> dict[str, Any]:
        """Normalize a single source row into canonical shape."""

        raw_name = extract_alias(row, "entity_name")
        normalized_name_value = normalize_name(raw_name)
        entity_uei = extract_alias(row, "entity_uei")
        parent_uei = extract_alias(row, "parent_uei")
        award_id = extract_alias(row, "award_id")
        project_id = extract_alias(row, "project_id") or award_id
        funding_source = extract_alias(row, "funding_source") or self.source_id
        agency = extract_alias(row, "agency")
        source_url = extract_alias(row, "source_url")
        source_date = extract_alias(row, "source_date")
        pop_state = extract_alias(row, "pop_state")
        pop_county = extract_alias(row, "pop_county")
        municipality = extract_alias(row, "municipality")
        geo_location = format_geo_location(pop_state, pop_county, municipality)
        obligation_amount = parse_amount(extract_alias(row, "obligation_amount"))

        entity_id = derive_entity_id(
            normalized_name_value=normalized_name_value,
            entity_uei=entity_uei,
            source_system=self.source_id,
        )

        if entity_uei:
            link_confidence = 0.98
        elif normalized_name_value and award_id:
            link_confidence = 0.75
        elif normalized_name_value:
            link_confidence = 0.6
        else:
            link_confidence = 0.4

        normalized = {
            "entity_id": entity_id,
            "parent_uei": parent_uei,
            "normalized_name": normalized_name_value,
            "award_id": award_id,
            "funding_source": funding_source,
            "obligation_amount": obligation_amount,
            "geo_location": geo_location,
            "project_id": project_id,
            "agency": agency,
            "source_system": self.source_id,
            "source_url": source_url,
            "source_date": source_date,
            "link_confidence": round(link_confidence, 4),
            "risk_score": 0.0,
            "municipality": municipality,
            "contract_type": extract_alias(row, "contract_type"),
            "award_status": extract_alias(row, "award_status"),
        }

        # Guarantee canonical keys are always present.
        for key in CANONICAL_CONTRACT_FIELDS + OPTIONAL_CANONICAL_FIELDS:
            normalized.setdefault(key, "")

        return normalized

    def normalize_records(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Normalize multiple source rows."""

        return [self.normalize_row(row) for row in rows]
