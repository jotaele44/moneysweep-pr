"""Financial flow master builders."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha1
from typing import Any

import pandas as pd


FINANCIAL_FLOW_COLUMNS = [
    "flow_id",
    "flow_type",
    "source_system",
    "funding_source",
    "award_id",
    "project_id",
    "entity_id",
    "upstream_entity_id",
    "downstream_asset_id",
    "municipality",
    "agency",
    "amount_type",
    "amount",
    "flow_date",
    "link_confidence",
    "evidence_path",
]


@dataclass(frozen=True)
class FinancialFlowResult:
    """Financial flow output bundle."""

    financial_flows_master: pd.DataFrame
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


def _stable_flow_id(parts: list[str]) -> str:
    seed = "|".join(str(part) for part in parts).encode("utf-8")
    return f"flow-{sha1(seed).hexdigest()[:16]}"


def _flow_type(source_system: str, funding_source: str) -> str:
    text = f"{source_system} {funding_source}".lower()
    if any(token in text for token in ["fema", "cor3", "recovery"]):
        return "recovery_execution"
    if any(token in text for token in ["hud", "cdbg", "drgr"]):
        return "housing_recovery_finance"
    if any(token in text for token in ["prasa", "aaa", "water"]):
        return "water_infrastructure_execution"
    if any(token in text for token in ["prepa", "luma", "genera", "energy"]):
        return "grid_infrastructure_execution"
    if any(token in text for token in ["emma", "msrb", "bond"]):
        return "capital_market_financing"
    if "municipal" in text:
        return "municipal_execution"
    return "contract_execution"


def build_financial_flows(execution_chain_master: pd.DataFrame) -> FinancialFlowResult:
    """Build financial flow rows from execution-chain links."""

    frame = execution_chain_master.copy()
    for col in [
        "source_system",
        "funding_source",
        "award_id",
        "project_id",
        "entity_id",
        "upstream_entity_id",
        "downstream_asset_id",
        "municipality",
        "agency",
        "obligation_amount",
        "source_date",
        "link_confidence",
        "evidence_path",
    ]:
        if col not in frame.columns:
            frame[col] = ""

    rows: list[dict[str, Any]] = []
    for _, record in frame.iterrows():
        source_system = str(record.get("source_system", "") or "").strip()
        funding_source = str(record.get("funding_source", "") or "").strip()
        award_id = str(record.get("award_id", "") or "").strip()
        project_id = str(record.get("project_id", "") or "").strip()
        upstream_entity_id = str(record.get("upstream_entity_id", "") or "").strip()
        downstream_asset_id = str(record.get("downstream_asset_id", "") or "").strip()
        amount = _safe_float(record.get("obligation_amount", 0.0))

        rows.append(
            {
                "flow_id": _stable_flow_id([source_system, award_id, project_id, upstream_entity_id, downstream_asset_id]),
                "flow_type": _flow_type(source_system, funding_source),
                "source_system": source_system,
                "funding_source": funding_source,
                "award_id": award_id,
                "project_id": project_id,
                "entity_id": str(record.get("entity_id", "") or "").strip(),
                "upstream_entity_id": upstream_entity_id,
                "downstream_asset_id": downstream_asset_id,
                "municipality": str(record.get("municipality", "") or "").strip(),
                "agency": str(record.get("agency", "") or "").strip(),
                "amount_type": "obligation_amount",
                "amount": round(amount, 2),
                "flow_date": str(record.get("source_date", "") or "").strip(),
                "link_confidence": _safe_float(record.get("link_confidence", 0.0)),
                "evidence_path": str(record.get("evidence_path", "") or "").strip(),
            }
        )

    output = pd.DataFrame(rows)
    if output.empty:
        output = pd.DataFrame(columns=FINANCIAL_FLOW_COLUMNS)
    else:
        for col in FINANCIAL_FLOW_COLUMNS:
            if col not in output.columns:
                output[col] = ""
        output = output[FINANCIAL_FLOW_COLUMNS]
        output = output.drop_duplicates(subset=["flow_id"], keep="first")

    total_amount = float(pd.to_numeric(output["amount"], errors="coerce").fillna(0.0).sum()) if not output.empty else 0.0
    avg_confidence = float(pd.to_numeric(output["link_confidence"], errors="coerce").fillna(0.0).mean()) if not output.empty else 0.0
    summary = {
        "rows_total": int(len(output)),
        "total_amount": round(total_amount, 2),
        "avg_link_confidence": round(avg_confidence, 4),
        "flow_type_counts": output["flow_type"].value_counts().to_dict() if not output.empty else {},
        "source_system_counts": output["source_system"].value_counts().to_dict() if not output.empty else {},
    }

    return FinancialFlowResult(financial_flows_master=output, summary=summary)
