"""Whole-row entity neighborhood drill-down for financial leaderboards.

The response preserves source-native records by dataset instead of synthesizing
one cross-source row. Canonical entity identity is asserted only for canonical_v1
entity IDs; UEI/FEC namespaces remain explicitly source-native unless an
independent canonical bridge exists.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
CANON = ROOT / "data" / "canonical_v1"
PROCESSED = ROOT / "data" / "staging" / "processed"


def _read(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path, dtype=str, low_memory=False).fillna("")
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    return frame.to_dict("records") if not frame.empty else []


def canonical_entity_drilldown(data: dict[str, pd.DataFrame], entity_id: str) -> dict[str, Any]:
    entities = data["entities"]
    entity_rows = entities[entities["entity_id"] == entity_id]
    if len(entity_rows) != 1:
        return {
            "entityId": entity_id,
            "identityState": "UNRESOLVED_CANONICAL_ENTITY_ID",
            "canonicalEntity": None,
            "datasets": {},
            "mapHandoff": {"state": "UNRESOLVED_NO_CANONICAL_ENTITY"},
        }
    entity = entity_rows.iloc[0].to_dict()
    contracts = data["contracts"]
    edges = data["edges"]
    municipalities = data["municipalities"]
    debt = _read(CANON / "debt_instruments.csv")
    lobbying = _read(CANON / "lobbying_records.csv")
    properties = _read(CANON / "properties.csv")

    contract_rows = contracts[
        (contracts["contractor_entity_id"] == entity_id)
        | (contracts["awarding_entity_id"] == entity_id)
    ]
    edge_rows = edges[
        (edges["source_node_id"] == entity_id) | (edges["target_node_id"] == entity_id)
    ]
    debt_rows = debt[debt.get("issuer_entity_id", pd.Series(dtype=str)) == entity_id] if not debt.empty else debt
    lobby_rows = lobbying[
        (lobbying.get("lobbyist_entity_id", pd.Series(dtype=str)) == entity_id)
        | (lobbying.get("client_entity_id", pd.Series(dtype=str)) == entity_id)
    ] if not lobbying.empty else lobbying
    property_rows = properties[properties.get("owner_entity_id", pd.Series(dtype=str)) == entity_id] if not properties.empty else properties

    located = edge_rows[
        (edge_rows.get("edge_type", pd.Series(dtype=str)) == "LOCATED_IN")
        & (edge_rows.get("source_node_id", pd.Series(dtype=str)) == entity_id)
    ]
    muni_ids = sorted(set(located.get("target_node_id", pd.Series(dtype=str)).astype(str)) - {""})
    muni_rows = municipalities[municipalities["municipality_id"].isin(muni_ids)] if muni_ids else municipalities.iloc[0:0]

    return {
        "entityId": entity_id,
        "identityState": "CANONICAL_V1_ENTITY_ID",
        "canonicalEntity": entity,
        "datasets": {
            "contracts": _records(contract_rows),
            "relationships": _records(edge_rows),
            "debtInstruments": _records(debt_rows),
            "lobbyingRecords": _records(lobby_rows),
            "properties": _records(property_rows),
        },
        "counts": {
            "contracts": len(contract_rows),
            "relationships": len(edge_rows),
            "debtInstruments": len(debt_rows),
            "lobbyingRecords": len(lobby_rows),
            "properties": len(property_rows),
        },
        "mapHandoff": {
            "state": "REFERENCE_ONLY_NO_CERTIFIED_GEOMETRY",
            "municipalities": _records(muni_rows),
            "municipalityIds": muni_ids,
            "geometryAuthority": "Spiderweb/TheHub spatial plane; MoneySweep does not promote municipality reference edges into geometry",
        },
    }


def source_native_drilldown(entity_id: str) -> dict[str, Any]:
    if entity_id.startswith("uei:"):
        uei = entity_id.split(":", 1)[1]
        path = PROCESSED / "pr_all_awards_master.csv"
        frame = _read(path)
        rows = frame[frame.get("recipient_uei", pd.Series(dtype=str)).astype(str).str.upper() == uei.upper()] if not frame.empty else frame
        return {
            "entityId": entity_id,
            "identityState": "SOURCE_NATIVE_UEI",
            "canonicalEntity": None,
            "datasets": {"federalAwards": _records(rows)},
            "counts": {"federalAwards": len(rows)},
            "mapHandoff": {"state": "UNRESOLVED_NO_AUTHORITATIVE_SPATIAL_BINDING"},
        }
    if entity_id.startswith("fec_committee:"):
        fec_id = entity_id.split(":", 1)[1]
        committees = _read(PROCESSED / "pr_campaign_finance_committees.csv")
        edges = _read(PROCESSED / "pr_campaign_finance_edges.csv")
        committee_rows = committees[committees.get("fec_committee_id", pd.Series(dtype=str)) == fec_id] if not committees.empty else committees
        edge_rows = edges[
            (edges.get("source_entity_id", pd.Series(dtype=str)) == fec_id)
            | (edges.get("target_entity_id", pd.Series(dtype=str)) == fec_id)
        ] if not edges.empty else edges
        return {
            "entityId": entity_id,
            "identityState": "AUTHORITATIVE_FEC_COMMITTEE_ID",
            "canonicalEntity": None,
            "datasets": {"committee": _records(committee_rows), "campaignFinanceEdges": _records(edge_rows)},
            "counts": {"committee": len(committee_rows), "campaignFinanceEdges": len(edge_rows)},
            "mapHandoff": {"state": "UNRESOLVED_NO_AUTHORITATIVE_SPATIAL_BINDING"},
        }
    return {
        "entityId": entity_id,
        "identityState": "UNRESOLVED_NAMESPACE",
        "canonicalEntity": None,
        "datasets": {},
        "mapHandoff": {"state": "UNRESOLVED"},
    }


def build_entity_drilldown(data: dict[str, pd.DataFrame], entity_id: str) -> dict[str, Any]:
    if entity_id.startswith("entity_"):
        return canonical_entity_drilldown(data, entity_id)
    return source_native_drilldown(entity_id)
