"""Evidence-preserving financial leaderboards for the diagnostic MoneySweep API.

The module deliberately refuses name-only aggregation.  Only adapters with a
stable entity identifier may produce ranked rows.  Unsupported ontology
categories remain visible with an explicit certification state rather than
silently synthesizing incomparable financial measures.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
from fastapi import APIRouter, HTTPException, Query

ROOT = Path(__file__).resolve().parents[2]
CANON = ROOT / "data" / "canonical_v1"
ONTOLOGY_PATH = ROOT / "config" / "financial_category_ontology.json"


def _ontology() -> dict[str, Any]:
    return json.loads(ONTOLOGY_PATH.read_text(encoding="utf-8"))


def _manifest(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    stat = path.stat()
    return {
        "path": str(path.relative_to(ROOT)),
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "modifiedAt": datetime.fromtimestamp(stat.st_mtime, tz=UTC).isoformat(),
    }


def _number(value: object) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if pd.notna(number) else None


def _year(value: object) -> int | None:
    text = str(value or "")
    return int(text[:4]) if len(text) >= 4 and text[:4].isdigit() else None


def _entity_locations(edges: pd.DataFrame) -> dict[str, set[str]]:
    result: dict[str, set[str]] = defaultdict(set)
    located = edges[edges["edge_type"] == "LOCATED_IN"]
    for _, row in located.iterrows():
        source = str(row.get("source_node_id") or "")
        target = str(row.get("target_node_id") or "")
        if source and target:
            result[source].add(target)
    return result


def _competition_ranks(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows.sort(key=lambda row: (-row["metricValue"], row["entityId"]))
    prior_value: float | None = None
    rank = 0
    for position, row in enumerate(rows, start=1):
        if prior_value is None or row["metricValue"] != prior_value:
            rank = position
            prior_value = row["metricValue"]
        row["rank"] = rank
    return rows


def _contract_award_ranking(
    data: dict[str, pd.DataFrame],
    *,
    limit: int,
    start_year: int | None,
    end_year: int | None,
    municipality: str | None,
    entity_type: str | None,
    currency: str | None,
) -> dict[str, Any]:
    contracts = data["contracts"]
    entities = data["entities"]
    edges = data["edges"]
    municipalities = data["municipalities"]

    entity_rows = {str(row["entity_id"]): row for _, row in entities.iterrows()}
    muni_name_to_id = {
        str(row.get("name") or "").casefold(): str(row.get("municipality_id") or "")
        for _, row in municipalities.iterrows()
    }
    locations = _entity_locations(edges)
    requested_muni_id = None
    if municipality:
        requested_muni_id = muni_name_to_id.get(municipality.casefold(), municipality)

    totals: dict[tuple[str, str], dict[str, Any]] = {}
    accounting = {
        "inputRecords": int(len(contracts)),
        "outOfScopeRecords": 0,
        "retainedRecords": 0,
        "excludedRecords": 0,
        "unresolvedRecords": 0,
    }

    for _, row in contracts.iterrows():
        contractor_id = str(row.get("contractor_entity_id") or "")
        entity = entity_rows.get(contractor_id)
        year = _year(row.get("start_date"))

        if start_year is not None and (year is None or year < start_year):
            accounting["outOfScopeRecords"] += 1
            continue
        if end_year is not None and (year is None or year > end_year):
            accounting["outOfScopeRecords"] += 1
            continue
        if entity_type and (entity is None or str(entity.get("entity_type") or "") != entity_type):
            accounting["outOfScopeRecords"] += 1
            continue

        if requested_muni_id:
            candidate_locations = locations.get(contractor_id, set())
            if len(candidate_locations) > 1:
                accounting["unresolvedRecords"] += 1
                continue
            if len(candidate_locations) == 0 or requested_muni_id not in candidate_locations:
                accounting["outOfScopeRecords"] += 1
                continue

        if not contractor_id or entity is None:
            accounting["unresolvedRecords"] += 1
            continue

        amount = _number(row.get("award_amount"))
        if amount is None:
            accounting["excludedRecords"] += 1
            continue

        row_currency = str(row.get("currency") or "USD").upper()
        if currency and row_currency != currency.upper():
            accounting["outOfScopeRecords"] += 1
            continue

        key = (contractor_id, row_currency)
        agg = totals.setdefault(
            key,
            {
                "entityId": contractor_id,
                "canonicalEntityId": contractor_id,
                "entityDisplayName": str(entity.get("name") or contractor_id),
                "entityType": str(entity.get("entity_type") or "") or None,
                "metricType": "AWARDED",
                "metricValue": 0.0,
                "currency": row_currency,
                "recordCount": 0,
                "sourceCount": set(),
                "sourceManifestationCount": set(),
                "entityResolutionState": "CANONICAL_V1_ENTITY_ID",
                "financialValueState": "MEASURED_SOURCE_VALUE",
                "previousRank": None,
                "rankDelta": None,
                "movementState": "OPEN_NO_PRIOR_SNAPSHOT",
            },
        )
        agg["metricValue"] += amount
        agg["recordCount"] += 1
        source_id = str(row.get("source_id") or "")
        source_ref = str(row.get("source_ref") or row.get("source_url") or "")
        if source_id:
            agg["sourceCount"].add(source_id)
        if source_ref:
            agg["sourceManifestationCount"].add(source_ref)
        accounting["retainedRecords"] += 1

    rows = []
    for agg in totals.values():
        agg["sourceCount"] = len(agg["sourceCount"])
        agg["sourceManifestationCount"] = len(agg["sourceManifestationCount"])
        rows.append(agg)

    # Never mix currencies in one ranked universe.  If the caller omitted a
    # currency and multiple currencies are present, fail closed.
    currencies = sorted({row["currency"] for row in rows})
    if len(currencies) > 1 and currency is None:
        raise HTTPException(
            409,
            detail={
                "state": "UNRESOLVED",
                "reason": "multiple currencies present; choose one currency explicitly",
                "currencies": currencies,
            },
        )

    _competition_ranks(rows)
    rows = [row for row in rows if row["rank"] <= limit]

    in_scope = (
        accounting["retainedRecords"]
        + accounting["excludedRecords"]
        + accounting["unresolvedRecords"]
    )
    accounting["inScopeRecords"] = in_scope
    accounting["arithmeticClosed"] = (
        accounting["inputRecords"]
        == accounting["outOfScopeRecords"] + in_scope
    )

    return {
        "categoryId": "contract_award",
        "categoryLabel": "Government contract awards",
        "metricType": "AWARDED",
        "certificationState": "PROVISIONAL",
        "rankingVersion": "moneysweep.leaderboard/v1",
        "computedAt": datetime.now(tz=UTC).isoformat(),
        "topN": limit,
        "tiesIncluded": True,
        "filters": {
            "startYear": start_year,
            "endYear": end_year,
            "municipality": municipality,
            "entityType": entity_type,
            "currency": currency or (currencies[0] if len(currencies) == 1 else None),
        },
        "accounting": accounting,
        "rows": rows,
        "sourceManifestations": [
            _manifest(CANON / "contracts.csv"),
            _manifest(CANON / "entities.csv"),
            _manifest(CANON / "edges.csv"),
            _manifest(CANON / "municipalities.csv"),
        ],
        "methodology": {
            "identity": "stable canonical_v1 contractor_entity_id only; names never establish identity",
            "aggregation": "signed award_amount summed by entity and currency",
            "ties": "competition ranking; all entities tied at rank N are returned",
            "nulls": "missing award_amount excluded and counted explicitly",
            "geography": "municipality filtering uses LOCATED_IN candidate sets; multi-location ties are unresolved",
            "history": "previousRank/rankDelta remain OPEN until a prior frozen ranking snapshot exists",
        },
    }


def create_router(data: dict[str, pd.DataFrame]) -> APIRouter:
    router = APIRouter(prefix="/leaderboards", tags=["leaderboards"])

    @router.get("/categories")
    def categories():
        ontology = _ontology()
        return {
            "schemaVersion": ontology["schema_version"],
            "rankingContractVersion": ontology["ranking_contract_version"],
            "rules": ontology["rules"],
            "categories": ontology["categories"],
        }

    @router.get("/top")
    def top(
        category: str = "contract_award",
        limit: int = Query(25, ge=1, le=25),
        start_year: int | None = None,
        end_year: int | None = None,
        municipality: str | None = None,
        entity_type: str | None = None,
        currency: str | None = None,
    ):
        ontology = _ontology()
        definitions = {item["id"]: item for item in ontology["categories"]}
        definition = definitions.get(category)
        if definition is None:
            raise HTTPException(404, f"unknown financial category: {category}")
        if definition.get("adapter") != "canonical_contracts":
            return {
                "categoryId": category,
                "categoryLabel": definition["label"],
                "metricType": definition["metric_type"],
                "certificationState": definition["certification_state"],
                "reason": definition["reason"],
                "rankingVersion": ontology["ranking_contract_version"],
                "rows": [],
                "topN": limit,
                "tiesIncluded": True,
            }
        if start_year is not None and end_year is not None and start_year > end_year:
            raise HTTPException(422, "start_year must be <= end_year")
        return _contract_award_ranking(
            data,
            limit=limit,
            start_year=start_year,
            end_year=end_year,
            municipality=municipality,
            entity_type=entity_type,
            currency=currency,
        )

    @router.get("/movers")
    def movers(category: str = "contract_award", limit: int = Query(10, ge=1, le=25)):
        return {
            "categoryId": category,
            "certificationState": "OPEN",
            "movementState": "OPEN_NO_PRIOR_SNAPSHOT",
            "reason": "A prior frozen ranking snapshot is required before rank movement can be computed without inventing history.",
            "rows": [],
            "limit": limit,
        }

    return router
