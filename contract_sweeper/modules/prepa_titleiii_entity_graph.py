"""PREPA Title III entity graph enrichment module.

This module converts PREPA PROMESA Title III service-matrix rows into
stakeholder graph nodes, classifies entities by sector, matches them against
contract/procurement/fuel/litigation datasets, and emits correlation flags with
evidence tiers and confidence scores.

It is intentionally an enrichment layer, not a misconduct detector. A match means
"stakeholder overlap" and requires additional corroboration before any allegation.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict, field
from enum import Enum
from pathlib import Path
import csv
import json
import re
from typing import Any, Iterable


class EvidenceTier(str, Enum):
    T1 = "T1_technical_primary"
    T2 = "T2_operational"
    T3 = "T3_eyewitness"
    T4 = "T4_secondary"


class EntitySector(str, Enum):
    LEGAL = "legal"
    FINANCE_BONDHOLDER = "finance_bondholder"
    ENERGY_FUEL = "energy_fuel"
    INFRASTRUCTURE_CONTRACTOR = "infrastructure_contractor"
    GOVERNMENT_PUBLIC_AUTHORITY = "government_public_authority"
    LABOR_PENSION = "labor_pension"
    INDIVIDUAL = "individual"
    UNKNOWN = "unknown"


class FlagType(str, Enum):
    PREPA_STAKEHOLDER_OVERLAP = "PREPA_STAKEHOLDER_OVERLAP"
    COUNSEL_COUNTERPARTY_OVERLAP = "COUNSEL_COUNTERPARTY_OVERLAP"
    FUEL_RESTRUCTURING_OVERLAP = "FUEL_RESTRUCTURING_OVERLAP"
    GRID_PRIVATIZATION_OVERLAP = "GRID_PRIVATIZATION_OVERLAP"
    FINANCIAL_CLAIMANT_OVERLAP = "FINANCIAL_CLAIMANT_OVERLAP"
    PUBLIC_AUTHORITY_INTERLOCK = "PUBLIC_AUTHORITY_INTERLOCK"


@dataclass(frozen=True)
class EntityNode:
    entity_id: str
    raw_name: str
    normalized_name: str
    sector: EntitySector
    source_document: str
    evidence_tier: EvidenceTier = EvidenceTier.T1
    service_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class GraphEdge:
    source_id: str
    target_id: str
    edge_type: str
    evidence_tier: EvidenceTier
    confidence: float
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CorrelationFlag:
    flag_type: FlagType
    entity_id: str
    normalized_name: str
    matched_dataset: str
    matched_record_id: str | None
    confidence: float
    evidence_tiers: list[EvidenceTier]
    rationale: str
    metadata: dict[str, Any] = field(default_factory=dict)


LEGAL_TERMS = (
    "LLP",
    "LAW",
    "LEGAL",
    "COUNSEL",
    "ABOG",
    "PSC",
    "P.S.C",
    "L.CDA",
    "LCDO",
    "ATTORNEY",
)
FINANCE_TERMS = (
    "BANK",
    "BOND",
    "CAPITAL",
    "ASSET",
    "FUND",
    "GUARANTY",
    "JPMORGAN",
    "SCOTIABANK",
    "GOLDMAN",
)
ENERGY_TERMS = ("ENERGY", "FUEL", "PETROLEUM", "VITOL", "PUMA", "ECOELECTRICA", "LNG", "POWER")
INFRA_TERMS = (
    "CONSTRUCTION",
    "CONTRACTOR",
    "ENGINEERING",
    "AECOM",
    "BLACK & VEATCH",
    "ALSTOM",
    "AIREKO",
    "INFRASTRUCTURE",
)
GOV_TERMS = (
    "AUTORIDAD",
    "AUTHORITY",
    "AAFAF",
    "AGENCY",
    "DEPARTMENT",
    "EPA",
    "TRUSTEE",
    "MUNICIPIO",
    "ADMINISTRACION",
)
LABOR_TERMS = ("UNION", "RETIRE", "RETIRO", "PENSION", "JUBIL", "EMPLOYEE", "EMPLEADOS")


def normalize_name(name: str) -> str:
    cleaned = re.sub(r"\s+", " ", name.upper()).strip()
    cleaned = cleaned.replace("&", " AND ")
    cleaned = re.sub(r"[^A-Z0-9 ]+", "", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def entity_id(normalized_name: str) -> str:
    return "prepa_titleiii:" + re.sub(r"[^a-z0-9]+", "_", normalized_name.lower()).strip("_")


def classify_sector(name: str) -> EntitySector:
    n = normalize_name(name)
    if any(term in n for term in ENERGY_TERMS):
        return EntitySector.ENERGY_FUEL
    if any(term in n for term in FINANCE_TERMS):
        return EntitySector.FINANCE_BONDHOLDER
    if any(term in n for term in LEGAL_TERMS):
        return EntitySector.LEGAL
    if any(term in n for term in INFRA_TERMS):
        return EntitySector.INFRASTRUCTURE_CONTRACTOR
    if any(term in n for term in GOV_TERMS):
        return EntitySector.GOVERNMENT_PUBLIC_AUTHORITY
    if any(term in n for term in LABOR_TERMS):
        return EntitySector.LABOR_PENSION
    if "," in name or len(n.split()) in (2, 3, 4):
        return EntitySector.INDIVIDUAL
    return EntitySector.UNKNOWN


def read_rows(path: str | Path) -> list[dict[str, str]]:
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def build_nodes(rows: Iterable[dict[str, str]], source_document: str) -> list[EntityNode]:
    nodes: dict[str, EntityNode] = {}
    for row in rows:
        raw_name = row.get("entity_name") or row.get("claim_name") or row.get("name") or ""
        raw_name = raw_name.strip()
        if not raw_name:
            continue
        normalized = normalize_name(raw_name)
        node = EntityNode(
            entity_id=entity_id(normalized),
            raw_name=raw_name,
            normalized_name=normalized,
            sector=classify_sector(raw_name),
            source_document=source_document,
            service_metadata={
                k: v for k, v in row.items() if k not in {"entity_name", "claim_name", "name"}
            },
        )
        nodes[node.entity_id] = node
    return list(nodes.values())


def _name_tokens(value: str) -> set[str]:
    return {token for token in normalize_name(value).split() if len(token) > 2}


def _overlap_score(a: str, b: str) -> float:
    ta, tb = _name_tokens(a), _name_tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def match_contract_records(
    nodes: Iterable[EntityNode],
    records: Iterable[dict[str, Any]],
    dataset_name: str,
    name_fields: tuple[str, ...] = (
        "recipient_name",
        "vendor_name",
        "awardee",
        "contractor",
        "entity_name",
        "name",
    ),
    threshold: float = 0.72,
) -> list[CorrelationFlag]:
    flags: list[CorrelationFlag] = []
    for node in nodes:
        for record in records:
            candidate_values = [
                str(record.get(field, "")) for field in name_fields if record.get(field)
            ]
            best = max(
                (_overlap_score(node.normalized_name, value) for value in candidate_values),
                default=0.0,
            )
            if best < threshold:
                continue
            flag_type = _flag_for_sector(node.sector)
            record_id = (
                record.get("record_id")
                or record.get("award_id")
                or record.get("piid")
                or record.get("id")
            )
            flags.append(
                CorrelationFlag(
                    flag_type=flag_type,
                    entity_id=node.entity_id,
                    normalized_name=node.normalized_name,
                    matched_dataset=dataset_name,
                    matched_record_id=str(record_id) if record_id is not None else None,
                    confidence=round(best, 3),
                    evidence_tiers=[EvidenceTier.T1],
                    rationale="PREPA Title III noticed stakeholder also appears in external contract/procurement-style record. This is a correlation flag, not a misconduct finding.",
                    metadata={"sector": node.sector.value, "matched_record": record},
                )
            )
    return flags


def _flag_for_sector(sector: EntitySector) -> FlagType:
    if sector == EntitySector.LEGAL:
        return FlagType.COUNSEL_COUNTERPARTY_OVERLAP
    if sector == EntitySector.ENERGY_FUEL:
        return FlagType.FUEL_RESTRUCTURING_OVERLAP
    if sector == EntitySector.INFRASTRUCTURE_CONTRACTOR:
        return FlagType.GRID_PRIVATIZATION_OVERLAP
    if sector == EntitySector.FINANCE_BONDHOLDER:
        return FlagType.FINANCIAL_CLAIMANT_OVERLAP
    if sector == EntitySector.GOVERNMENT_PUBLIC_AUTHORITY:
        return FlagType.PUBLIC_AUTHORITY_INTERLOCK
    return FlagType.PREPA_STAKEHOLDER_OVERLAP


def export_graph(
    nodes: list[EntityNode], flags: list[CorrelationFlag], output_path: str | Path
) -> None:
    payload = {
        "module": "prepa_titleiii_entity_graph",
        "nodes": [asdict(node) for node in nodes],
        "correlation_flags": [asdict(flag) for flag in flags],
        "warning": "Correlation output is not an allegation engine. Require multi-source corroboration before investigative conclusions.",
    }
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def run(
    service_matrix_csv: str | Path,
    output_json: str | Path,
    source_document: str = "PREPA Title III service matrix",
) -> dict[str, Any]:
    rows = read_rows(service_matrix_csv)
    nodes = build_nodes(rows, source_document=source_document)
    export_graph(nodes, [], output_json)
    return {"nodes": len(nodes), "flags": 0, "output": str(output_json)}
