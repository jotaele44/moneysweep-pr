"""Entity resolution with parent UEI collapse and confidence scoring."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha1
import re
from typing import Any

import pandas as pd
from rapidfuzz import fuzz

from contract_sweeper.normalization.canonical_contracts import normalize_name


ENTITIES_RESOLVED_COLUMNS = [
    "entity_id",
    "parent_uei",
    "normalized_name",
    "source_system",
    "link_confidence",
    "alias",
    "tax_id",
    "cage_code",
    "resolved_from",
    "canonical_name",
    "record_count",
    "total_obligation",
    "review_required",
    "review_reason",
]

LOW_CONFIDENCE_COLUMNS = [
    "alias",
    "canonical_name",
    "proposed_entity_id",
    "proposed_parent_uei",
    "link_confidence",
    "resolved_from",
    "source_system",
    "record_count",
    "total_obligation",
    "review_reason",
]


@dataclass(frozen=True)
class ResolutionResult:
    """Resolution result bundle."""

    entities_resolved: pd.DataFrame
    alias_registry: dict[str, Any]
    low_confidence_review_queue: pd.DataFrame
    high_value_unresolved_entities: pd.DataFrame
    summary: dict[str, Any]


def _safe_float(value: Any) -> float:
    if value is None:
        return 0.0
    text = str(value).strip().replace(",", "").replace("$", "")
    if text == "":
        return 0.0
    try:
        return float(text)
    except ValueError:
        return 0.0


def _stable_entity_id(value: str) -> bool:
    if not value:
        return False
    candidate = value.strip()
    if candidate == "":
        return False
    return not candidate.lower().startswith("anon-") and not candidate.lower().startswith("anonr-")


def _match_key(name: str) -> str:
    """Normalize split legal suffix tokens before fuzzy matching."""
    key = name.upper().strip()
    key = re.sub(r"\\bL\\s+L\\s+C\\b", "LLC", key)
    key = re.sub(r"\\bL\\s+L\\s+P\\b", "LLP", key)
    key = re.sub(r"\\bI\\s+N\\s+C\\b", "INC", key)
    key = re.sub(r"\\bC\\s+O\\s+R\\s+P\\b", "CORP", key)
    key = re.sub(r"\\s+", " ", key).strip()
    return key


def _similarity(lhs: str, rhs: str) -> float:
    """Compute fuzzy similarity with legal-suffix-aware normalization."""
    raw = float(fuzz.token_set_ratio(lhs, rhs))
    keyed = float(fuzz.token_set_ratio(_match_key(lhs), _match_key(rhs)))
    return max(raw, keyed)


def _join_unique(values: pd.Series) -> str:
    unique = sorted({str(v).strip() for v in values if str(v).strip()})
    return ";".join(unique)


def _most_common_non_empty(values: pd.Series) -> str:
    cleaned = [str(v).strip() for v in values if str(v).strip()]
    if not cleaned:
        return ""
    counts: dict[str, int] = {}
    for item in cleaned:
        counts[item] = counts.get(item, 0) + 1
    return max(counts.items(), key=lambda pair: pair[1])[0]


def _most_common_stable_entity(values: pd.Series) -> str:
    cleaned = [str(v).strip() for v in values if _stable_entity_id(str(v).strip())]
    if not cleaned:
        return ""
    counts: dict[str, int] = {}
    for item in cleaned:
        counts[item] = counts.get(item, 0) + 1
    return max(counts.items(), key=lambda pair: pair[1])[0]


def _build_alias_frame(contracts: pd.DataFrame) -> pd.DataFrame:
    required_cols = ["entity_id", "parent_uei", "normalized_name", "source_system", "obligation_amount"]
    frame = contracts.copy()
    for col in required_cols:
        if col not in frame.columns:
            frame[col] = ""

    frame["alias"] = frame["normalized_name"].fillna("").astype(str).apply(normalize_name)
    frame["source_system"] = frame["source_system"].fillna("").astype(str).str.strip()
    frame["entity_id"] = frame["entity_id"].fillna("").astype(str).str.strip()
    frame["parent_uei"] = frame["parent_uei"].fillna("").astype(str).str.strip()
    frame["obligation_amount_num"] = frame["obligation_amount"].apply(_safe_float)

    frame = frame[frame["alias"].str.strip() != ""].copy()

    grouped = (
        frame.groupby("alias", dropna=False)
        .agg(
            record_count=("alias", "size"),
            total_obligation=("obligation_amount_num", "sum"),
            source_system=("source_system", _join_unique),
            deterministic_parent_uei=("parent_uei", _most_common_non_empty),
            deterministic_entity_id=("entity_id", _most_common_stable_entity),
        )
        .reset_index()
    )

    grouped["canonical_name"] = grouped["alias"]
    return grouped


def _resolve_aliases(
    alias_frame: pd.DataFrame,
    fuzzy_threshold_high: float,
    fuzzy_threshold_medium: float,
    review_threshold: float,
) -> pd.DataFrame:
    resolved_rows: list[dict[str, Any]] = []

    anchors: list[dict[str, str]] = []
    for _, row in alias_frame.iterrows():
        parent_uei = str(row.get("deterministic_parent_uei", "") or "")
        entity_id = str(row.get("deterministic_entity_id", "") or "")
        alias = str(row["alias"])

        if parent_uei:
            anchors.append(
                {
                    "alias": alias,
                    "entity_id": parent_uei,
                    "parent_uei": parent_uei,
                    "method": "parent_uei",
                }
            )
        elif entity_id:
            anchors.append(
                {
                    "alias": alias,
                    "entity_id": entity_id,
                    "parent_uei": "",
                    "method": "entity_id",
                }
            )

    anchor_by_alias = {anchor["alias"]: anchor for anchor in anchors}

    for _, row in alias_frame.iterrows():
        alias = str(row["alias"])
        parent_uei = str(row.get("deterministic_parent_uei", "") or "")
        entity_id = str(row.get("deterministic_entity_id", "") or "")
        record_count = int(row.get("record_count", 0) or 0)
        total_obligation = float(row.get("total_obligation", 0.0) or 0.0)
        source_system = str(row.get("source_system", "") or "")

        resolved_entity_id = ""
        resolved_parent_uei = ""
        canonical_name = alias
        resolved_from = ""
        confidence = 0.0

        if alias in anchor_by_alias:
            anchor = anchor_by_alias[alias]
            resolved_entity_id = anchor["entity_id"]
            resolved_parent_uei = anchor["parent_uei"]
            canonical_name = alias
            if anchor["method"] == "parent_uei":
                resolved_from = "parent_uei"
                confidence = 0.99
            else:
                resolved_from = "entity_id"
                confidence = 0.95
        else:
            best_anchor = None
            best_score = 0.0
            for anchor in anchors:
                score = _similarity(alias, anchor["alias"])
                if score > best_score:
                    best_score = score
                    best_anchor = anchor

            if best_anchor is not None and best_score >= fuzzy_threshold_high:
                resolved_entity_id = best_anchor["entity_id"]
                resolved_parent_uei = best_anchor["parent_uei"]
                canonical_name = best_anchor["alias"]
                resolved_from = "fuzzy_high"
                confidence = min(0.97, 0.9 + ((best_score - fuzzy_threshold_high) / max(1.0, 100.0 - fuzzy_threshold_high)) * 0.07)
            elif best_anchor is not None and best_score >= fuzzy_threshold_medium:
                resolved_entity_id = best_anchor["entity_id"]
                resolved_parent_uei = best_anchor["parent_uei"]
                canonical_name = best_anchor["alias"]
                resolved_from = "fuzzy_medium"
                confidence = min(
                    0.92,
                    0.8
                    + (
                        (best_score - fuzzy_threshold_medium)
                        / max(1.0, fuzzy_threshold_high - fuzzy_threshold_medium)
                    )
                    * 0.12,
                )
            else:
                digest = sha1(alias.encode("utf-8")).hexdigest()[:16]
                resolved_entity_id = f"anonr-{digest}"
                resolved_parent_uei = ""
                canonical_name = alias
                resolved_from = "new_entity"
                confidence = 0.55

        review_required = confidence < review_threshold or resolved_from in {"fuzzy_medium", "new_entity"}
        if resolved_from == "new_entity":
            review_reason = "no deterministic parent/entity id and no strong fuzzy match"
        elif resolved_from == "fuzzy_medium":
            review_reason = "medium-confidence fuzzy alias match"
        elif confidence < review_threshold:
            review_reason = "confidence below review threshold"
        else:
            review_reason = ""

        resolved_rows.append(
            {
                "entity_id": resolved_entity_id,
                "parent_uei": resolved_parent_uei or parent_uei,
                "normalized_name": canonical_name,
                "source_system": source_system,
                "link_confidence": round(confidence, 4),
                "alias": alias,
                "tax_id": "",
                "cage_code": "",
                "resolved_from": resolved_from,
                "canonical_name": canonical_name,
                "record_count": record_count,
                "total_obligation": round(total_obligation, 2),
                "review_required": review_required,
                "review_reason": review_reason,
            }
        )

    resolved = pd.DataFrame(resolved_rows)
    if resolved.empty:
        return pd.DataFrame(columns=ENTITIES_RESOLVED_COLUMNS)

    for col in ENTITIES_RESOLVED_COLUMNS:
        if col not in resolved.columns:
            resolved[col] = ""

    return resolved[ENTITIES_RESOLVED_COLUMNS]


def _build_alias_registry(resolved: pd.DataFrame, summary: dict[str, Any]) -> dict[str, Any]:
    records = []
    for _, row in resolved.iterrows():
        records.append(
            {
                "alias": row["alias"],
                "canonical_name": row["canonical_name"],
                "entity_id": row["entity_id"],
                "parent_uei": row["parent_uei"],
                "link_confidence": float(row["link_confidence"]),
                "resolved_from": row["resolved_from"],
                "source_system": row["source_system"],
            }
        )

    return {
        "version": 1,
        "summary": summary,
        "aliases": records,
    }


def resolve_entities(
    contracts: pd.DataFrame,
    fuzzy_threshold_high: float = 93.0,
    fuzzy_threshold_medium: float = 88.0,
    review_threshold: float = 0.85,
    high_value_threshold: float = 1_000_000.0,
) -> ResolutionResult:
    """Resolve entity aliases and collapse to parent UEI where possible."""

    alias_frame = _build_alias_frame(contracts)
    resolved = _resolve_aliases(
        alias_frame=alias_frame,
        fuzzy_threshold_high=fuzzy_threshold_high,
        fuzzy_threshold_medium=fuzzy_threshold_medium,
        review_threshold=review_threshold,
    )

    if resolved.empty:
        low_conf = pd.DataFrame(columns=LOW_CONFIDENCE_COLUMNS)
        high_value_unresolved = pd.DataFrame(columns=LOW_CONFIDENCE_COLUMNS)
        summary = {
            "aliases_total": 0,
            "resolved_total": 0,
            "review_queue_total": 0,
            "high_value_unresolved_total": 0,
            "resolution_rate": 0.0,
        }
        alias_registry = _build_alias_registry(resolved, summary)
        return ResolutionResult(
            entities_resolved=resolved,
            alias_registry=alias_registry,
            low_confidence_review_queue=low_conf,
            high_value_unresolved_entities=high_value_unresolved,
            summary=summary,
        )

    low_conf = resolved[resolved["review_required"]].copy()
    low_conf = low_conf.rename(
        columns={
            "entity_id": "proposed_entity_id",
            "parent_uei": "proposed_parent_uei",
        }
    )
    for col in LOW_CONFIDENCE_COLUMNS:
        if col not in low_conf.columns:
            low_conf[col] = ""
    low_conf = low_conf[LOW_CONFIDENCE_COLUMNS]

    high_value_unresolved = low_conf[
        (low_conf["resolved_from"] == "new_entity")
        & (low_conf["total_obligation"].astype(float) >= float(high_value_threshold))
    ].copy()

    resolved_total = int((resolved["resolved_from"] != "new_entity").sum())
    total_aliases = int(len(resolved))
    summary = {
        "aliases_total": total_aliases,
        "resolved_total": resolved_total,
        "review_queue_total": int(len(low_conf)),
        "high_value_unresolved_total": int(len(high_value_unresolved)),
        "resolution_rate": round((resolved_total / total_aliases) if total_aliases else 0.0, 4),
        "review_threshold": float(review_threshold),
        "fuzzy_threshold_high": float(fuzzy_threshold_high),
        "fuzzy_threshold_medium": float(fuzzy_threshold_medium),
    }

    alias_registry = _build_alias_registry(resolved, summary)

    return ResolutionResult(
        entities_resolved=resolved,
        alias_registry=alias_registry,
        low_confidence_review_queue=low_conf,
        high_value_unresolved_entities=high_value_unresolved,
        summary=summary,
    )
