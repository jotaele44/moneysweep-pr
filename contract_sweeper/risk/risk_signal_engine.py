"""Probabilistic risk signal builders."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha1
import json
from typing import Any

import pandas as pd


RISK_ALERT_COLUMNS = [
    "alert_id",
    "alert_type",
    "indicator_label",
    "entity_id",
    "project_id",
    "award_id",
    "source_system",
    "funding_source",
    "municipality",
    "asset_id",
    "risk_score",
    "link_confidence",
    "amount",
    "source_date",
    "evidence_path",
    "probabilistic_assessment",
    "recommended_review_action",
]

RISK_REVIEW_COLUMNS = [
    "alert_id",
    "alert_type",
    "entity_id",
    "project_id",
    "award_id",
    "review_reason",
    "risk_score",
    "link_confidence",
    "amount",
    "evidence_path",
]

ENTITY_BEHAVIOR_COLUMNS = [
    "entity_id",
    "total_amount",
    "flow_count",
    "project_count",
    "asset_count",
    "source_system_count",
    "avg_link_confidence",
    "max_single_flow_amount",
    "latest_flow_date",
    "differential_change_ratio",
]

DEFINITIVE_TERMS = {
    "corruption",
    "criminal",
    "definitive",
    "fraud",
    "guilty",
    "illegal",
    "proven",
}


@dataclass(frozen=True)
class RiskSignalResult:
    """Risk signal output bundle."""

    risk_alerts_master: pd.DataFrame
    high_risk_projects_geojson: dict[str, Any]
    entity_behavior_history: pd.DataFrame
    risk_review_queue: pd.DataFrame
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


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _stable_alert_id(parts: list[Any]) -> str:
    seed = "|".join(_text(part) for part in parts).encode("utf-8")
    return f"risk-{sha1(seed).hexdigest()[:16]}"


def _ensure_columns(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    output = frame.copy()
    for col in columns:
        if col not in output.columns:
            output[col] = ""
    return output


def _rules_value(rules: dict[str, Any] | None, key: str, default: float) -> float:
    raw = (rules or {}).get(key, default)
    return _safe_float(raw) or float(default)


def _keyword_tokens(keywords: dict[str, Any] | None) -> set[str]:
    tokens: set[str] = set()
    for raw_values in (keywords or {}).values():
        if isinstance(raw_values, list):
            tokens.update(str(value).strip().lower() for value in raw_values if str(value).strip())
    return tokens


def _critical_asset_tokens(critical_assets: pd.DataFrame | None) -> set[str]:
    if critical_assets is None or critical_assets.empty:
        return {"water", "power", "hospital", "bridge", "school", "wastewater"}

    frame = _ensure_columns(critical_assets, ["asset_keyword", "asset_category"])
    tokens: set[str] = set()
    for _, row in frame.iterrows():
        tokens.add(_text(row.get("asset_keyword")).lower())
        tokens.add(_text(row.get("asset_category")).lower())
    return {token for token in tokens if token}


def _assessment(indicator_label: str, reason: str) -> str:
    return f"Possible indicator: {indicator_label}. This may warrant review because {reason}."


def _sanitize_probabilistic_language(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame
    output = frame.copy()
    text_columns = ["alert_type", "indicator_label", "probabilistic_assessment", "recommended_review_action"]
    for col in text_columns:
        output[col] = output[col].fillna("").astype(str)
        lowered = output[col].str.lower()
        for term in DEFINITIVE_TERMS:
            if lowered.str.contains(term, regex=False).any():
                output[col] = output[col].str.replace(term, "risk indicator", case=False, regex=False)
                lowered = output[col].str.lower()
    return output


def _alert_row(
    *,
    alert_type: str,
    indicator_label: str,
    entity_id: str,
    project_id: str,
    award_id: str,
    source_system: str,
    funding_source: str,
    municipality: str,
    asset_id: str,
    risk_score: float,
    link_confidence: float,
    amount: float,
    source_date: str,
    evidence_path: str,
    reason: str,
    action: str,
) -> dict[str, Any]:
    alert_id = _stable_alert_id([alert_type, entity_id, project_id, award_id, asset_id, source_date])
    return {
        "alert_id": alert_id,
        "alert_type": alert_type,
        "indicator_label": indicator_label,
        "entity_id": entity_id,
        "project_id": project_id,
        "award_id": award_id,
        "source_system": source_system,
        "funding_source": funding_source,
        "municipality": municipality,
        "asset_id": asset_id,
        "risk_score": round(min(1.0, max(0.0, risk_score)), 4),
        "link_confidence": round(min(1.0, max(0.0, link_confidence)), 4),
        "amount": round(amount, 2),
        "source_date": source_date,
        "evidence_path": evidence_path,
        "probabilistic_assessment": _assessment(indicator_label, reason),
        "recommended_review_action": action,
    }


def _contract_alerts(
    contracts_master: pd.DataFrame,
    keywords: dict[str, Any] | None,
    rules: dict[str, Any] | None,
    critical_assets: pd.DataFrame | None,
) -> list[dict[str, Any]]:
    frame = _ensure_columns(
        contracts_master,
        [
            "entity_id",
            "project_id",
            "award_id",
            "source_system",
            "funding_source",
            "municipality",
            "geo_location",
            "obligation_amount",
            "link_confidence",
            "risk_score",
            "source_date",
            "source_url",
            "normalized_name",
            "agency",
            "contract_type",
        ],
    )
    high_value_threshold = _rules_value(rules, "high_value_threshold", 1_000_000.0)
    low_confidence_threshold = _rules_value(rules, "low_confidence_threshold", 0.75)
    keyword_tokens = _keyword_tokens(keywords)
    asset_tokens = _critical_asset_tokens(critical_assets)

    rows: list[dict[str, Any]] = []
    for _, record in frame.iterrows():
        amount = _safe_float(record.get("obligation_amount"))
        link_confidence = _safe_float(record.get("link_confidence"))
        base_risk = _safe_float(record.get("risk_score"))
        municipality = _text(record.get("municipality")) or _text(record.get("geo_location")).split(",")[0].strip()
        source_date = _text(record.get("source_date"))
        evidence_path = _text(record.get("source_url"))
        text_blob = " ".join(
            [
                _text(record.get("source_system")),
                _text(record.get("funding_source")),
                _text(record.get("agency")),
                _text(record.get("contract_type")),
                _text(record.get("normalized_name")),
                _text(record.get("project_id")),
            ]
        ).lower()

        common = {
            "entity_id": _text(record.get("entity_id")),
            "project_id": _text(record.get("project_id")),
            "award_id": _text(record.get("award_id")),
            "source_system": _text(record.get("source_system")),
            "funding_source": _text(record.get("funding_source")),
            "municipality": municipality,
            "asset_id": "",
            "link_confidence": link_confidence,
            "amount": amount,
            "source_date": source_date,
            "evidence_path": evidence_path,
        }

        if amount >= high_value_threshold and link_confidence < low_confidence_threshold:
            rows.append(
                _alert_row(
                    alert_type="possible_low_confidence_high_value_linkage",
                    indicator_label="High-value record has lower linkage confidence",
                    risk_score=max(base_risk, 0.82),
                    reason="the amount is material and the cross-source link confidence is below the review threshold",
                    action="Review source documents and confirm entity, project, and asset linkage before downstream use.",
                    **common,
                )
            )

        if any(token for token in keyword_tokens if token and token in text_blob):
            rows.append(
                _alert_row(
                    alert_type="possible_procurement_pressure_indicator",
                    indicator_label="Text contains procurement pressure terms",
                    risk_score=max(base_risk, 0.68),
                    reason="the normalized source text includes pressure or influence-related terms",
                    action="Check whether the terms reflect routine context or a meaningful change event.",
                    **common,
                )
            )

        if any(token in text_blob for token in asset_tokens):
            rows.append(
                _alert_row(
                    alert_type="possible_critical_asset_exposure",
                    indicator_label="Contract appears related to a critical asset category",
                    risk_score=max(base_risk, 0.72),
                    reason="the record references an asset category that may be operationally critical",
                    action="Confirm asset mapping and compare with execution-chain and graph outputs before escalation.",
                    **common,
                )
            )

    return rows


def _execution_chain_alerts(
    execution_chain_master: pd.DataFrame,
    rules: dict[str, Any] | None,
    critical_assets: pd.DataFrame | None,
) -> list[dict[str, Any]]:
    frame = _ensure_columns(
        execution_chain_master,
        [
            "entity_id",
            "project_id",
            "award_id",
            "source_system",
            "funding_source",
            "municipality",
            "downstream_asset_id",
            "obligation_amount",
            "link_confidence",
            "source_date",
            "evidence_path",
        ],
    )
    low_confidence_threshold = _rules_value(rules, "low_confidence_threshold", 0.75)
    high_value_threshold = _rules_value(rules, "high_value_threshold", 1_000_000.0)
    asset_tokens = _critical_asset_tokens(critical_assets)

    rows: list[dict[str, Any]] = []
    for _, record in frame.iterrows():
        amount = _safe_float(record.get("obligation_amount"))
        link_confidence = _safe_float(record.get("link_confidence"))
        asset_id = _text(record.get("downstream_asset_id"))
        text_blob = " ".join(
            [
                _text(record.get("source_system")),
                _text(record.get("funding_source")),
                _text(record.get("municipality")),
                asset_id,
            ]
        ).lower()
        common = {
            "entity_id": _text(record.get("entity_id")),
            "project_id": _text(record.get("project_id")),
            "award_id": _text(record.get("award_id")),
            "source_system": _text(record.get("source_system")),
            "funding_source": _text(record.get("funding_source")),
            "municipality": _text(record.get("municipality")),
            "asset_id": asset_id,
            "link_confidence": link_confidence,
            "amount": amount,
            "source_date": _text(record.get("source_date")),
            "evidence_path": _text(record.get("evidence_path")),
        }

        if amount >= high_value_threshold and link_confidence < low_confidence_threshold:
            rows.append(
                _alert_row(
                    alert_type="possible_execution_chain_review_gap",
                    indicator_label="Execution-chain link combines material value with lower confidence",
                    risk_score=0.84,
                    reason="the chain row should not support claims without manual corroboration",
                    action="Send to linkage review queue and inspect upstream/downstream identifiers.",
                    **common,
                )
            )

        if asset_id and any(token in text_blob for token in asset_tokens):
            rows.append(
                _alert_row(
                    alert_type="possible_chain_critical_asset_indicator",
                    indicator_label="Execution chain touches a critical asset category",
                    risk_score=0.71 if link_confidence >= low_confidence_threshold else 0.79,
                    reason="critical asset linkage can amplify operational risk if other indicators are present",
                    action="Verify the asset category and compare with municipality/project controls.",
                    **common,
                )
            )

    return rows


def build_entity_behavior_history(financial_flows_master: pd.DataFrame) -> pd.DataFrame:
    """Aggregate entity behavior history from financial flows."""

    frame = _ensure_columns(
        financial_flows_master,
        [
            "entity_id",
            "amount",
            "flow_id",
            "project_id",
            "downstream_asset_id",
            "source_system",
            "link_confidence",
            "flow_date",
        ],
    )
    if frame.empty:
        return pd.DataFrame(columns=ENTITY_BEHAVIOR_COLUMNS)

    frame = frame.copy()
    frame["amount"] = frame["amount"].apply(_safe_float)
    frame["link_confidence"] = pd.to_numeric(frame["link_confidence"], errors="coerce").fillna(0.0)
    frame["flow_date_parsed"] = pd.to_datetime(frame["flow_date"], errors="coerce")

    grouped = (
        frame.groupby("entity_id", dropna=False)
        .agg(
            total_amount=("amount", "sum"),
            flow_count=("flow_id", "count"),
            project_count=("project_id", lambda values: len({str(value).strip() for value in values if str(value).strip()})),
            asset_count=(
                "downstream_asset_id",
                lambda values: len({str(value).strip() for value in values if str(value).strip()}),
            ),
            source_system_count=(
                "source_system",
                lambda values: len({str(value).strip() for value in values if str(value).strip()}),
            ),
            avg_link_confidence=("link_confidence", "mean"),
            max_single_flow_amount=("amount", "max"),
            latest_flow_date=("flow_date", "max"),
        )
        .reset_index()
    )

    ratios: dict[str, float] = {}
    for entity_id, entity_rows in frame.groupby("entity_id", dropna=False):
        ordered = entity_rows.sort_values("flow_date_parsed")
        positive = ordered["amount"][ordered["amount"] > 0]
        if len(positive) < 2:
            ratios[str(entity_id)] = 1.0
            continue
        previous = float(positive.iloc[:-1].median())
        latest = float(positive.iloc[-1])
        ratios[str(entity_id)] = round(latest / previous, 4) if previous else 1.0

    grouped["differential_change_ratio"] = grouped["entity_id"].map(lambda value: ratios.get(str(value), 1.0))
    grouped["total_amount"] = grouped["total_amount"].round(2)
    grouped["avg_link_confidence"] = grouped["avg_link_confidence"].round(4)
    grouped["max_single_flow_amount"] = grouped["max_single_flow_amount"].round(2)

    for col in ENTITY_BEHAVIOR_COLUMNS:
        if col not in grouped.columns:
            grouped[col] = ""
    return grouped[ENTITY_BEHAVIOR_COLUMNS]


def _behavior_alerts(
    behavior_history: pd.DataFrame,
    financial_flows_master: pd.DataFrame,
    rules: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    change_multiplier = _rules_value(rules, "differential_change_multiplier", 2.0)
    high_value_threshold = _rules_value(rules, "high_value_threshold", 1_000_000.0)
    flows = _ensure_columns(
        financial_flows_master,
        [
            "entity_id",
            "project_id",
            "award_id",
            "source_system",
            "funding_source",
            "municipality",
            "downstream_asset_id",
            "amount",
            "link_confidence",
            "flow_date",
            "evidence_path",
        ],
    )
    rows: list[dict[str, Any]] = []
    for _, behavior in behavior_history.iterrows():
        ratio = _safe_float(behavior.get("differential_change_ratio"))
        total_amount = _safe_float(behavior.get("total_amount"))
        if ratio < change_multiplier or total_amount < high_value_threshold:
            continue
        entity_id = _text(behavior.get("entity_id"))
        latest_rows = flows[flows["entity_id"].astype(str) == entity_id].copy()
        if latest_rows.empty:
            continue
        latest_rows["flow_date_parsed"] = pd.to_datetime(latest_rows["flow_date"], errors="coerce")
        latest = latest_rows.sort_values("flow_date_parsed").iloc[-1]
        rows.append(
            _alert_row(
                alert_type="possible_differential_change_event",
                indicator_label="Entity financial flow changed materially versus prior behavior",
                entity_id=entity_id,
                project_id=_text(latest.get("project_id")),
                award_id=_text(latest.get("award_id")),
                source_system=_text(latest.get("source_system")),
                funding_source=_text(latest.get("funding_source")),
                municipality=_text(latest.get("municipality")),
                asset_id=_text(latest.get("downstream_asset_id")),
                risk_score=0.86,
                link_confidence=_safe_float(latest.get("link_confidence")),
                amount=_safe_float(latest.get("amount")),
                source_date=_text(latest.get("flow_date")),
                evidence_path=_text(latest.get("evidence_path")),
                reason="latest observed flow is materially larger than the entity baseline",
                action="Compare against prior awards, amendments, and project milestones before assigning a risk interpretation.",
            )
        )
    return rows


def _optional_context_alerts(
    contracts_master: pd.DataFrame,
    asset_control_graph_outputs: pd.DataFrame | None,
    lobbying_tables: pd.DataFrame | None,
    rules: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    del rules

    contracts = _ensure_columns(
        contracts_master,
        [
            "entity_id",
            "project_id",
            "award_id",
            "source_system",
            "funding_source",
            "municipality",
            "geo_location",
            "obligation_amount",
            "link_confidence",
            "source_date",
            "source_url",
            "normalized_name",
        ],
    )
    if contracts.empty:
        return []

    rows: list[dict[str, Any]] = []
    entity_ids = {value for value in contracts["entity_id"].fillna("").astype(str).str.strip() if value}
    names = {value for value in contracts["normalized_name"].fillna("").astype(str).str.upper().str.strip() if value}

    if lobbying_tables is not None and not lobbying_tables.empty:
        lobbying = _ensure_columns(lobbying_tables, ["entity_id", "normalized_name", "source_system", "evidence_path"])
        lobbying_matches = lobbying[
            lobbying["entity_id"].fillna("").astype(str).str.strip().isin(entity_ids)
            | lobbying["normalized_name"].fillna("").astype(str).str.upper().str.strip().isin(names)
        ]
        for _, match in lobbying_matches.head(25).iterrows():
            entity_id = _text(match.get("entity_id"))
            contract_match = contracts[contracts["entity_id"].astype(str) == entity_id]
            if contract_match.empty:
                contract_match = contracts[
                    contracts["normalized_name"].fillna("").astype(str).str.upper().str.strip()
                    == _text(match.get("normalized_name")).upper()
                ]
            if contract_match.empty:
                continue
            contract = contract_match.iloc[0]
            amount = _safe_float(contract.get("obligation_amount"))
            rows.append(
                _alert_row(
                    alert_type="possible_influence_context_overlap",
                    indicator_label="Lobbying or cabilderos context overlaps with a contracting entity",
                    entity_id=_text(contract.get("entity_id")) or entity_id,
                    project_id=_text(contract.get("project_id")),
                    award_id=_text(contract.get("award_id")),
                    source_system=_text(contract.get("source_system")),
                    funding_source=_text(contract.get("funding_source")),
                    municipality=_text(contract.get("municipality")) or _text(contract.get("geo_location")).split(",")[0].strip(),
                    asset_id="",
                    risk_score=0.74,
                    link_confidence=_safe_float(contract.get("link_confidence")),
                    amount=amount,
                    source_date=_text(contract.get("source_date")),
                    evidence_path=_text(match.get("evidence_path")) or _text(contract.get("source_url")),
                    reason="a normalized influence-context table references the same entity or alias",
                    action="Review timing, role, and source evidence before treating the overlap as meaningful.",
                )
            )

    if asset_control_graph_outputs is not None and not asset_control_graph_outputs.empty:
        graph = _ensure_columns(asset_control_graph_outputs, ["entity_id", "asset_id", "control_score", "evidence_path"])
        graph_matches = graph[graph["entity_id"].fillna("").astype(str).str.strip().isin(entity_ids)]
        for _, match in graph_matches.head(25).iterrows():
            control_score = _safe_float(match.get("control_score"))
            if control_score < 0.6:
                continue
            entity_id = _text(match.get("entity_id"))
            contract_match = contracts[contracts["entity_id"].astype(str) == entity_id]
            if contract_match.empty:
                continue
            contract = contract_match.iloc[0]
            rows.append(
                _alert_row(
                    alert_type="possible_asset_control_context_overlap",
                    indicator_label="Asset-control context overlaps with a contracting entity",
                    entity_id=entity_id,
                    project_id=_text(contract.get("project_id")),
                    award_id=_text(contract.get("award_id")),
                    source_system=_text(contract.get("source_system")),
                    funding_source=_text(contract.get("funding_source")),
                    municipality=_text(contract.get("municipality")) or _text(contract.get("geo_location")).split(",")[0].strip(),
                    asset_id=_text(match.get("asset_id")),
                    risk_score=max(0.7, min(0.9, control_score)),
                    link_confidence=_safe_float(contract.get("link_confidence")),
                    amount=_safe_float(contract.get("obligation_amount")),
                    source_date=_text(contract.get("source_date")),
                    evidence_path=_text(match.get("evidence_path")) or _text(contract.get("source_url")),
                    reason="an optional asset-control context table references the same entity",
                    action="Confirm the graph context after Phase 8 stability checks before escalation.",
                )
            )

    return rows


def _build_review_queue(alerts: pd.DataFrame, rules: dict[str, Any] | None) -> pd.DataFrame:
    if alerts.empty:
        return pd.DataFrame(columns=RISK_REVIEW_COLUMNS)

    review_threshold = _rules_value(rules, "review_threshold", 0.65)
    low_confidence_threshold = _rules_value(rules, "low_confidence_threshold", 0.75)
    frame = alerts.copy()
    frame["risk_score"] = pd.to_numeric(frame["risk_score"], errors="coerce").fillna(0.0)
    frame["link_confidence"] = pd.to_numeric(frame["link_confidence"], errors="coerce").fillna(0.0)
    queue = frame[(frame["risk_score"] >= review_threshold) | (frame["link_confidence"] < low_confidence_threshold)].copy()
    queue["review_reason"] = queue.apply(
        lambda row: "risk indicator score above review threshold"
        if float(row["risk_score"]) >= review_threshold
        else "link confidence below review threshold",
        axis=1,
    )
    for col in RISK_REVIEW_COLUMNS:
        if col not in queue.columns:
            queue[col] = ""
    return queue[RISK_REVIEW_COLUMNS]


def build_high_risk_geojson(alerts: pd.DataFrame) -> dict[str, Any]:
    """Build a minimal local GeoJSON feature collection for high-risk projects."""

    if alerts.empty:
        return {"type": "FeatureCollection", "features": []}

    features: list[dict[str, Any]] = []
    for _, row in alerts.iterrows():
        features.append(
            {
                "type": "Feature",
                "geometry": None,
                "properties": {
                    "alert_id": _text(row.get("alert_id")),
                    "alert_type": _text(row.get("alert_type")),
                    "entity_id": _text(row.get("entity_id")),
                    "project_id": _text(row.get("project_id")),
                    "award_id": _text(row.get("award_id")),
                    "municipality": _text(row.get("municipality")),
                    "asset_id": _text(row.get("asset_id")),
                    "risk_score": _safe_float(row.get("risk_score")),
                    "assessment": _text(row.get("probabilistic_assessment")),
                },
            }
        )
    return {"type": "FeatureCollection", "features": features}


def assert_probabilistic_alert_language(alerts: pd.DataFrame) -> None:
    """Raise when alert language uses unsupported definitive terms."""

    if alerts.empty:
        return
    text = " ".join(
        alerts[col].fillna("").astype(str).str.lower().str.cat(sep=" ")
        for col in ["alert_type", "indicator_label", "probabilistic_assessment", "recommended_review_action"]
        if col in alerts.columns
    )
    present = sorted(term for term in DEFINITIVE_TERMS if term in text)
    if present:
        raise ValueError(f"Risk alerts contain unsupported definitive terms: {', '.join(present)}")


def build_risk_signals(
    contracts_master: pd.DataFrame,
    execution_chain_master: pd.DataFrame,
    entities_resolved: pd.DataFrame,
    financial_flows_master: pd.DataFrame,
    keywords: dict[str, Any] | None = None,
    rules: dict[str, Any] | None = None,
    critical_assets: pd.DataFrame | None = None,
    asset_control_graph_outputs: pd.DataFrame | None = None,
    lobbying_tables: pd.DataFrame | None = None,
) -> RiskSignalResult:
    """Build local probabilistic risk signals from normalized and linked inputs."""

    del entities_resolved

    behavior = build_entity_behavior_history(financial_flows_master)
    rows: list[dict[str, Any]] = []
    rows.extend(_contract_alerts(contracts_master, keywords, rules, critical_assets))
    rows.extend(_execution_chain_alerts(execution_chain_master, rules, critical_assets))
    rows.extend(_behavior_alerts(behavior, financial_flows_master, rules))
    rows.extend(_optional_context_alerts(contracts_master, asset_control_graph_outputs, lobbying_tables, rules))

    alerts = pd.DataFrame(rows)
    if alerts.empty:
        alerts = pd.DataFrame(columns=RISK_ALERT_COLUMNS)
    else:
        for col in RISK_ALERT_COLUMNS:
            if col not in alerts.columns:
                alerts[col] = ""
        alerts = alerts[RISK_ALERT_COLUMNS]
        alerts = alerts.drop_duplicates(subset=["alert_id"], keep="first")
        alerts = _sanitize_probabilistic_language(alerts)

    assert_probabilistic_alert_language(alerts)
    review_queue = _build_review_queue(alerts, rules)
    geojson = build_high_risk_geojson(alerts)

    summary = {
        "rows_total": int(len(alerts)),
        "review_queue_total": int(len(review_queue)),
        "entity_behavior_rows_total": int(len(behavior)),
        "alert_type_counts": alerts["alert_type"].value_counts().to_dict() if not alerts.empty else {},
        "probabilistic_language_ok": True,
        "geojson_feature_count": int(len(geojson["features"])),
        "input_rows": {
            "contracts_master": int(len(contracts_master)),
            "execution_chain_master": int(len(execution_chain_master)),
            "financial_flows_master": int(len(financial_flows_master)),
        },
    }

    try:
        json.dumps(geojson)
    except TypeError as exc:
        raise ValueError("Risk GeoJSON output is not JSON serializable") from exc

    return RiskSignalResult(
        risk_alerts_master=alerts,
        high_risk_projects_geojson=geojson,
        entity_behavior_history=behavior,
        risk_review_queue=review_queue,
        summary=summary,
    )
