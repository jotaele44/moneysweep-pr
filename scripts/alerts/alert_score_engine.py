"""Explainable scoring for project-emergence records."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .alert_event_schema import AlertLevel, ProjectStage

OFFICIAL_PROCUREMENT = {"fpds", "usaspending", "sam_gov", "compras_pr", "p3a", "contract", "contracts"}
PERMIT_LAND_USE = {"ogpe", "junta_planificacion", "planning", "drna", "epa", "municipio_records"}
BUDGET_FUNDING = {"aaafa", "cor3", "fema", "cdbg_dr", "hud", "doe", "preb", "luma", "prepa", "genera"}
MEDIA_ONLY = {"media", "press", "news", "press_release"}


@dataclass(slots=True)
class ScoreResult:
    score: int
    level: str
    confidence: float
    reasons: list[str] = field(default_factory=list)
    stage: int = 0
    requires_spiderweb: bool = False


def infer_stage(record: dict[str, Any]) -> int:
    text = " ".join(str(record.get(k, "")) for k in ("description", "title", "award_category", "source_dataset")).lower()
    source = str(record.get("source_dataset") or record.get("source") or "").lower()
    if any(term in text for term in ("amendment", "modification", "change order", "expansion")):
        return ProjectStage.EXPANSION_AMENDMENT
    if any(term in text for term in ("maintenance", "security", "operations", "staffing", "concession")):
        return ProjectStage.OPERATIONS_LAYER
    if any(term in text for term in ("construction", "site work", "materials", "earthwork", "build")):
        return ProjectStage.CONSTRUCTION_PROCUREMENT
    if any(term in text for term in ("road", "water", "power", "substation", "drainage", "telecom", "utility")):
        return ProjectStage.INFRASTRUCTURE_PREPARATION
    if any(term in text for term in ("engineering", "design", "study", "legal", "consulting", "architecture")):
        return ProjectStage.PROFESSIONAL_SERVICES
    if source in BUDGET_FUNDING or any(term in text for term in ("grant", "funding", "budget", "bond", "appropriation")):
        return ProjectStage.FUNDING_VISIBILITY
    if source in PERMIT_LAND_USE or any(term in text for term in ("permit", "zoning", "environmental", "public hearing", "land use")):
        return ProjectStage.PLANNING_VISIBILITY
    if any(term in text for term in ("llc", "corporation", "registered agent", "entity")):
        return ProjectStage.ENTITY_FORMATION
    return ProjectStage.RUMOR_MEDIA_ONLY


def score_record(record: dict[str, Any], project: dict[str, Any], thresholds_config: dict[str, Any], source_family_count: int = 1, vendor_recurrent: bool = False, stage_advanced: bool = False) -> ScoreResult:
    scoring = thresholds_config.get("scoring", {})
    thresholds = thresholds_config.get("thresholds", {})
    reasons: list[str] = []
    score = 0
    text = " ".join(str(record.get(k, "")) for k in record.keys()).lower()
    canonical = str(project.get("canonical_name", "")).lower()
    aliases = [str(a).lower() for a in project.get("aliases", [])]
    source = str(record.get("source_dataset") or record.get("source") or "").lower()
    amount = _as_float(record.get("obligated_amount") or record.get("amount") or record.get("award_amount"))

    if canonical and canonical in text:
        score += scoring.get("exact_project_name_match", 30); reasons.append("exact_project_name_match")
    elif any(alias and alias in text for alias in aliases):
        score += scoring.get("alias_match", 20); reasons.append("alias_match")
    if source in OFFICIAL_PROCUREMENT:
        score += scoring.get("official_procurement_source", 20); reasons.append("official_procurement_source")
    if source in PERMIT_LAND_USE:
        score += scoring.get("permit_land_use_environmental_source", 20); reasons.append("permit_land_use_environmental_source")
    if source in BUDGET_FUNDING:
        score += scoring.get("budget_funding_bond_source", 15); reasons.append("budget_funding_bond_source")
    if source in MEDIA_ONLY:
        score += scoring.get("media_only_penalty", -20); reasons.append("media_only_penalty")

    municipios = [str(m).lower() for m in project.get("locations", {}).get("municipios", [])]
    if municipios and any(m and m in text for m in municipios):
        score += scoring.get("matching_municipio_or_aoi", 10); reasons.append("matching_municipio_or_aoi")
    if str(record.get("agency") or record.get("awarding_agency") or "").strip():
        score += scoring.get("matching_agency", 10); reasons.append("matching_agency")
    if str(record.get("parcel_id") or record.get("coordinates") or record.get("facility") or "").strip():
        score += scoring.get("matching_parcel_coordinate_facility", 10); reasons.append("matching_parcel_coordinate_facility")
    if vendor_recurrent:
        score += scoring.get("vendor_recurrence", 15); reasons.append("vendor_recurrence")
    if amount is not None and amount >= thresholds_config.get("amount_thresholds", {}).get("default_major_amount", 1_000_000):
        score += scoring.get("amount_exceeds_threshold", 10); reasons.append("amount_exceeds_threshold")
    if source_family_count >= 3:
        score += scoring.get("three_or_more_source_families", 15); reasons.append("three_or_more_source_families")
    elif source_family_count >= 2:
        score += scoring.get("two_source_families", 10); reasons.append("two_source_families")
    if stage_advanced:
        score += scoring.get("stage_advance", 10); reasons.append("stage_advance")

    stage = int(infer_stage(record))
    score = max(0, min(100, int(score)))
    level = classify_level(score, thresholds, source_family_count, stage, amount)
    spiderweb_threshold = int(project.get("spiderweb_trigger_threshold", thresholds.get("review", 55)))
    confidence = round(min(0.99, max(0.0, score / 100)), 2)
    return ScoreResult(score, level, confidence, reasons, stage, score >= spiderweb_threshold and level != AlertLevel.BACKGROUND)


def classify_level(score: int, thresholds: dict[str, Any], source_family_count: int, stage: int, amount: float | None) -> str:
    watch = int(thresholds.get("watch", 35)); review = int(thresholds.get("review", 55)); urgent = int(thresholds.get("urgent", 75)); critical = int(thresholds.get("critical", 90))
    if score >= critical and source_family_count >= 2 and (stage >= 5 or (amount or 0) >= 1_000_000):
        return AlertLevel.CRITICAL
    if score >= urgent:
        return AlertLevel.URGENT
    if score >= review:
        return AlertLevel.REVIEW
    if score >= watch:
        return AlertLevel.WATCH
    return AlertLevel.BACKGROUND


def _as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(str(value).replace("$", "").replace(",", ""))
    except ValueError:
        return None
