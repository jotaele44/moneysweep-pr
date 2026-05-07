"""Execution-chain linkage builders."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha1
from typing import Any

import pandas as pd
from rapidfuzz import fuzz

from contract_sweeper.normalization.canonical_contracts import normalize_name


EXECUTION_CHAIN_MASTER_COLUMNS = [
    "entity_id",
    "project_id",
    "funding_source",
    "source_system",
    "link_confidence",
    "upstream_entity_id",
    "downstream_asset_id",
    "municipality",
    "award_id",
    "obligation_amount",
    "agency",
    "source_date",
    "link_method",
    "evidence_path",
    "review_required",
    "review_reason",
]

EXECUTION_CHAIN_PER_ASSET_COLUMNS = [
    "asset_id",
    "municipality",
    "funding_source",
    "source_system",
    "linked_contract_count",
    "unique_entities",
    "total_obligation",
    "avg_link_confidence",
    "low_confidence_count",
    "coverage_ratio",
]

REVIEW_QUEUE_COLUMNS = [
    "entity_id",
    "project_id",
    "funding_source",
    "source_system",
    "link_confidence",
    "upstream_entity_id",
    "downstream_asset_id",
    "municipality",
    "award_id",
    "obligation_amount",
    "link_method",
    "review_reason",
]


@dataclass(frozen=True)
class ChainLinkageResult:
    """Result bundle for execution-chain linkage."""

    execution_chain_master: pd.DataFrame
    execution_chain_per_asset: pd.DataFrame
    low_confidence_review_queue: pd.DataFrame
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


def _normalize_col(frame: pd.DataFrame, name: str) -> pd.Series:
    if name not in frame.columns:
        return pd.Series([""] * len(frame), index=frame.index)
    return frame[name].fillna("").astype(str).str.strip()


def _parse_municipality(geo_location: str) -> str:
    text = str(geo_location).strip()
    if text == "":
        return ""
    return text.split(",")[0].strip()


def _asset_category(source_system: str, funding_source: str, agency: str) -> str:
    text = f"{source_system} {funding_source} {agency}".lower()
    if any(token in text for token in ["prasa", "aaa", "water", "aqueduct"]):
        return "water"
    if any(token in text for token in ["prepa", "luma", "genera", "grid", "energy", "power"]):
        return "energy"
    if any(token in text for token in ["fema", "cor3", "hud", "cdbg", "recovery", "drgr"]):
        return "recovery"
    if any(token in text for token in ["municipal", "municipio"]):
        return "municipal"
    if any(token in text for token in ["bond", "emma", "msrb", "finance"]):
        return "finance"
    return "general"


def _derive_asset_id(
    source_system: str,
    funding_source: str,
    agency: str,
    project_id: str,
    award_id: str,
    municipality: str,
    entity_id: str,
) -> str:
    category = _asset_category(source_system, funding_source, agency)
    anchor = project_id or award_id or municipality or entity_id
    if not anchor:
        return ""
    digest = sha1(f"{category}|{source_system}|{anchor}".encode("utf-8")).hexdigest()[:12]
    return f"asset:{category}:{digest}"


def _build_resolution_index(resolved_entities: pd.DataFrame) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    alias_index: dict[str, dict[str, Any]] = {}
    anchors: list[dict[str, Any]] = []

    if resolved_entities.empty:
        return alias_index, anchors

    frame = resolved_entities.copy()
    for col in ["alias", "normalized_name", "entity_id", "parent_uei", "link_confidence", "canonical_name", "source_system"]:
        if col not in frame.columns:
            frame[col] = ""

    for _, row in frame.iterrows():
        alias = normalize_name(str(row.get("alias") or row.get("normalized_name") or ""))
        if not alias:
            continue
        payload = {
            "entity_id": str(row.get("entity_id", "") or "").strip(),
            "parent_uei": str(row.get("parent_uei", "") or "").strip(),
            "canonical_name": normalize_name(str(row.get("canonical_name", alias) or alias)),
            "link_confidence": float(row.get("link_confidence", 0.0) or 0.0),
            "source_system": str(row.get("source_system", "") or "").strip(),
        }
        alias_index[alias] = payload

        anchor_id = payload["parent_uei"] or payload["entity_id"]
        if anchor_id:
            anchors.append({"alias": alias, **payload})

    return alias_index, anchors


def _resolve_entity_for_contract(
    entity_id: str,
    normalized_name_value: str,
    alias_index: dict[str, dict[str, Any]],
    anchors: list[dict[str, Any]],
    fuzzy_high: float,
    fuzzy_medium: float,
) -> tuple[str, str, float, str, str]:
    if entity_id:
        for anchor in anchors:
            if anchor["entity_id"] == entity_id:
                upstream = anchor["parent_uei"] or anchor["entity_id"]
                return upstream, anchor["canonical_name"], 0.99, "direct_entity_id", ""

    alias_key = normalize_name(normalized_name_value)
    if alias_key in alias_index:
        matched = alias_index[alias_key]
        upstream = matched["parent_uei"] or matched["entity_id"]
        conf = max(float(matched["link_confidence"]), 0.9)
        return upstream, matched["canonical_name"], min(0.99, conf), "exact_alias", ""

    best = None
    best_score = 0.0
    for anchor in anchors:
        score = float(fuzz.token_set_ratio(alias_key, anchor["alias"]))
        if score > best_score:
            best_score = score
            best = anchor

    if best is not None and best_score >= fuzzy_high:
        upstream = best["parent_uei"] or best["entity_id"]
        conf = min(0.97, 0.9 + ((best_score - fuzzy_high) / max(1.0, 100.0 - fuzzy_high)) * 0.07)
        return upstream, best["canonical_name"], conf, "fuzzy_alias_high", ""

    if best is not None and best_score >= fuzzy_medium:
        upstream = best["parent_uei"] or best["entity_id"]
        conf = min(0.89, 0.78 + ((best_score - fuzzy_medium) / max(1.0, fuzzy_high - fuzzy_medium)) * 0.11)
        return upstream, best["canonical_name"], conf, "fuzzy_alias_medium", "medium-confidence fuzzy alias match"

    if entity_id:
        return entity_id, alias_key, 0.62, "fallback_entity_id", "entity unresolved in alias registry"

    digest = sha1(alias_key.encode("utf-8")).hexdigest()[:16] if alias_key else "unknown"
    return f"anonl-{digest}", alias_key, 0.5, "unresolved_entity", "no deterministic or fuzzy entity match"


def _build_master_rows(
    contracts: pd.DataFrame,
    resolved_entities: pd.DataFrame,
    fuzzy_high: float,
    fuzzy_medium: float,
    review_threshold: float,
) -> pd.DataFrame:
    alias_index, anchors = _build_resolution_index(resolved_entities)

    frame = contracts.copy()
    for col in [
        "entity_id",
        "project_id",
        "funding_source",
        "source_system",
        "award_id",
        "obligation_amount",
        "agency",
        "source_date",
        "geo_location",
        "normalized_name",
        "source_url",
    ]:
        if col not in frame.columns:
            frame[col] = ""

    rows: list[dict[str, Any]] = []

    for _, record in frame.iterrows():
        raw_entity_id = str(record.get("entity_id", "") or "").strip()
        project_id = str(record.get("project_id", "") or "").strip()
        award_id = str(record.get("award_id", "") or "").strip()
        funding_source = str(record.get("funding_source", "") or "").strip()
        source_system = str(record.get("source_system", "") or "").strip()
        agency = str(record.get("agency", "") or "").strip()
        source_date = str(record.get("source_date", "") or "").strip()
        geo_location = str(record.get("geo_location", "") or "").strip()
        normalized_name_value = str(record.get("normalized_name", "") or "").strip()
        municipality = _parse_municipality(geo_location)
        obligation_amount = _safe_float(record.get("obligation_amount", 0.0))

        upstream_entity_id, canonical_name, entity_conf, link_method, reason = _resolve_entity_for_contract(
            entity_id=raw_entity_id,
            normalized_name_value=normalized_name_value,
            alias_index=alias_index,
            anchors=anchors,
            fuzzy_high=fuzzy_high,
            fuzzy_medium=fuzzy_medium,
        )

        downstream_asset_id = _derive_asset_id(
            source_system=source_system,
            funding_source=funding_source,
            agency=agency,
            project_id=project_id,
            award_id=award_id,
            municipality=municipality,
            entity_id=upstream_entity_id,
        )

        project_conf = 0.95 if project_id else 0.72
        asset_conf = 0.92 if downstream_asset_id else 0.55
        link_confidence = round(min(0.99, 0.6 * entity_conf + 0.2 * project_conf + 0.2 * asset_conf), 4)

        review_required = bool(link_confidence < review_threshold or link_method in {"fuzzy_alias_medium", "unresolved_entity", "fallback_entity_id"})
        if reason:
            review_reason = reason
        elif link_confidence < review_threshold:
            review_reason = "link confidence below review threshold"
        else:
            review_reason = ""

        evidence_path = str(record.get("source_url", "") or "")

        rows.append(
            {
                "entity_id": raw_entity_id,
                "project_id": project_id,
                "funding_source": funding_source,
                "source_system": source_system,
                "link_confidence": link_confidence,
                "upstream_entity_id": upstream_entity_id,
                "downstream_asset_id": downstream_asset_id,
                "municipality": municipality,
                "award_id": award_id,
                "obligation_amount": round(obligation_amount, 2),
                "agency": agency,
                "source_date": source_date,
                "link_method": link_method,
                "evidence_path": evidence_path,
                "review_required": review_required,
                "review_reason": review_reason,
                "canonical_name": canonical_name,
            }
        )

    master = pd.DataFrame(rows)
    if master.empty:
        return pd.DataFrame(columns=EXECUTION_CHAIN_MASTER_COLUMNS)

    for col in EXECUTION_CHAIN_MASTER_COLUMNS:
        if col not in master.columns:
            master[col] = ""

    master = master.drop_duplicates(subset=["source_system", "award_id", "upstream_entity_id", "downstream_asset_id"], keep="first")
    return master[EXECUTION_CHAIN_MASTER_COLUMNS]


def _build_per_asset(master: pd.DataFrame) -> pd.DataFrame:
    if master.empty:
        return pd.DataFrame(columns=EXECUTION_CHAIN_PER_ASSET_COLUMNS)

    frame = master.copy()
    frame["obligation_amount"] = frame["obligation_amount"].apply(_safe_float)
    frame["link_confidence"] = pd.to_numeric(frame["link_confidence"], errors="coerce").fillna(0.0)

    grouped = (
        frame.groupby(["downstream_asset_id", "municipality", "funding_source", "source_system"], dropna=False)
        .agg(
            linked_contract_count=("award_id", "count"),
            unique_entities=("upstream_entity_id", lambda values: len({str(v).strip() for v in values if str(v).strip()})),
            total_obligation=("obligation_amount", "sum"),
            avg_link_confidence=("link_confidence", "mean"),
            low_confidence_count=("link_confidence", lambda values: int((pd.Series(values) < 0.85).sum())),
        )
        .reset_index()
    )

    grouped = grouped.rename(columns={"downstream_asset_id": "asset_id"})
    grouped["coverage_ratio"] = (
        grouped["linked_contract_count"] - grouped["low_confidence_count"]
    ) / grouped["linked_contract_count"].replace({0: 1})

    grouped["avg_link_confidence"] = grouped["avg_link_confidence"].round(4)
    grouped["total_obligation"] = grouped["total_obligation"].round(2)
    grouped["coverage_ratio"] = grouped["coverage_ratio"].round(4)

    for col in EXECUTION_CHAIN_PER_ASSET_COLUMNS:
        if col not in grouped.columns:
            grouped[col] = ""

    return grouped[EXECUTION_CHAIN_PER_ASSET_COLUMNS]


def _build_review_queue(master: pd.DataFrame) -> pd.DataFrame:
    if master.empty:
        return pd.DataFrame(columns=REVIEW_QUEUE_COLUMNS)

    queue = master[master["review_required"]].copy()
    for col in REVIEW_QUEUE_COLUMNS:
        if col not in queue.columns:
            queue[col] = ""
    return queue[REVIEW_QUEUE_COLUMNS]


def build_execution_chain(
    contracts: pd.DataFrame,
    resolved_entities: pd.DataFrame,
    fuzzy_high: float = 93.0,
    fuzzy_medium: float = 88.0,
    review_threshold: float = 0.85,
    linkage_target: float = 0.90,
) -> ChainLinkageResult:
    """Build execution chain master and per-asset linkage outputs."""

    master = _build_master_rows(
        contracts=contracts,
        resolved_entities=resolved_entities,
        fuzzy_high=fuzzy_high,
        fuzzy_medium=fuzzy_medium,
        review_threshold=review_threshold,
    )

    per_asset = _build_per_asset(master)
    review_queue = _build_review_queue(master)

    total_rows = len(master)
    linked_rows = (
        int(
            (
                (
                    master["upstream_entity_id"].astype(str).str.strip() != ""
                )
                & (
                    master["downstream_asset_id"].astype(str).str.strip() != ""
                )
                & (pd.to_numeric(master["link_confidence"], errors="coerce").fillna(0.0) >= 0.7)
            ).sum()
        )
        if total_rows
        else 0
    )

    linkage_rate = round((linked_rows / total_rows) if total_rows else 0.0, 4)

    summary = {
        "rows_total": total_rows,
        "rows_linked": linked_rows,
        "cross_layer_linkage_rate": linkage_rate,
        "cross_layer_linkage_target": float(linkage_target),
        "target_met": bool(linkage_rate >= linkage_target),
        "review_queue_total": int(len(review_queue)),
        "asset_rows_total": int(len(per_asset)),
    }

    return ChainLinkageResult(
        execution_chain_master=master,
        execution_chain_per_asset=per_asset,
        low_confidence_review_queue=review_queue,
        summary=summary,
    )
