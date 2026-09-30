"""Evidence-preserving financial leaderboard API.

The public API delegates every executable financial category to a separately
bounded adapter. Names are never identity evidence, non-equivalent measures are
never mixed, and historical movement is exposed only from hash-verified
snapshots that match the exact requested ranking universe.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
from fastapi import APIRouter, HTTPException, Query

from server.backend.leaderboard_adapters import (
    _competition_ranks,
    contract_awards,
    run_adapter,
)
from server.backend.leaderboard_entities import build_entity_drilldown
from server.backend.leaderboard_history import compare, list_snapshots
from server.backend.leaderboard_investigation import build_signals

ROOT = Path(__file__).resolve().parents[2]
ONTOLOGY_PATH = ROOT / "config" / "financial_category_ontology.json"


def _ontology() -> dict[str, Any]:
    return json.loads(ONTOLOGY_PATH.read_text(encoding="utf-8"))


def _unsupported(definition: dict[str, Any], limit: int | None) -> dict[str, Any]:
    return {
        "categoryId": definition["id"],
        "categoryLabel": definition["label"],
        "metricType": definition["metric_type"],
        "certificationState": definition["certification_state"],
        "reason": definition["reason"],
        "rankingVersion": _ontology()["ranking_contract_version"],
        "rows": [],
        "topN": limit,
        "tiesIncluded": True,
        "candidateCount": 0,
        "sourceManifestations": [],
    }


def build_ranking(
    data: dict[str, pd.DataFrame],
    *,
    category: str = "contract_award",
    limit: int | None = 25,
    start_year: int | None = None,
    end_year: int | None = None,
    municipality: str | None = None,
    entity_type: str | None = None,
    currency: str | None = None,
) -> dict[str, Any]:
    """Build one bounded ranking without hiding unsupported categories.

    ``limit=None`` returns the complete candidate universe and is reserved for
    immutable snapshot materialization. Ordinary API callers are capped at 25.
    """
    if limit is not None and not 1 <= limit <= 25:
        raise HTTPException(422, "limit must be between 1 and 25")
    if start_year is not None and end_year is not None and start_year > end_year:
        raise HTTPException(422, "start_year must be <= end_year")

    ontology = _ontology()
    definitions = {item["id"]: item for item in ontology["categories"]}
    definition = definitions.get(category)
    if definition is None:
        raise HTTPException(404, f"unknown financial category: {category}")
    adapter_id = definition.get("adapter")
    if not adapter_id:
        return _unsupported(definition, limit)

    result = run_adapter(
        adapter_id,
        data,
        limit=limit,
        start_year=start_year,
        end_year=end_year,
        municipality=municipality,
        entity_type=entity_type,
        currency=currency,
    )
    if result.get("rankingVersion") != ontology["ranking_contract_version"]:
        raise HTTPException(
            500,
            detail={
                "state": "FAIL",
                "reason": "leaderboard adapter ranking-contract drift",
                "expected": ontology["ranking_contract_version"],
                "observed": result.get("rankingVersion"),
                "category": category,
            },
        )
    return result


# Compatibility seam retained for existing focused tests and downstream code.
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
    return contract_awards(
        data,
        limit=limit,
        start_year=start_year,
        end_year=end_year,
        municipality=municipality,
        entity_type=entity_type,
        currency=currency,
    )


def _history_key(value: dict[str, Any]) -> tuple[str, str, str, str, str]:
    return (
        str(value.get("categoryId") or ""),
        str(value.get("metricType") or ""),
        str(value.get("rankingVersion") or ""),
        json.dumps(value.get("filters") or {}, sort_keys=True, separators=(",", ":")),
        json.dumps(value.get("currencies") or [], sort_keys=True, separators=(",", ":")),
    )


def _movers_for_ranking(ranking: dict[str, Any], *, limit: int = 10) -> dict[str, Any]:
    """Select history only from the exact ranking universe requested now."""
    category = str(ranking.get("categoryId") or "")
    target_key = _history_key(ranking)
    snapshots = [row for row in list_snapshots(category) if _history_key(row) == target_key]
    if len(snapshots) < 2:
        return {
            "categoryId": category,
            "certificationState": "OPEN",
            "movementState": "OPEN_NO_COMPARABLE_PRIOR_SNAPSHOT",
            "reason": "At least two valid frozen snapshots matching the exact category/measure/version/filter/currency universe are required.",
            "snapshotCount": len(snapshots),
            "rows": [],
            "limit": limit,
            "filters": ranking.get("filters") or {},
            "currencies": ranking.get("currencies") or [],
        }
    result = compare(snapshots[-2], snapshots[-1], limit=limit)
    result["filters"] = ranking.get("filters") or {}
    result["currencies"] = ranking.get("currencies") or []
    return result


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
        return build_ranking(
            data,
            category=category,
            limit=limit,
            start_year=start_year,
            end_year=end_year,
            municipality=municipality,
            entity_type=entity_type,
            currency=currency,
        )

    @router.get("/history")
    def history(category: str = "contract_award"):
        snapshots = list_snapshots(category)
        return {
            "categoryId": category,
            "snapshotCount": len(snapshots),
            "snapshots": [
                {
                    "snapshotId": row.get("snapshotId"),
                    "capturedAt": row.get("capturedAt"),
                    "snapshotSha256": row.get("snapshotSha256"),
                    "metricType": row.get("metricType"),
                    "rankingVersion": row.get("rankingVersion"),
                    "candidateCount": row.get("candidateCount"),
                    "filters": row.get("filters"),
                    "currencies": row.get("currencies"),
                    "certificationState": row.get("certificationState"),
                    "runtimeManifest": row.get("runtimeManifest"),
                }
                for row in snapshots
            ],
        }

    @router.get("/movers")
    def movers(
        category: str = "contract_award",
        limit: int = Query(10, ge=1, le=25),
        start_year: int | None = None,
        end_year: int | None = None,
        municipality: str | None = None,
        entity_type: str | None = None,
        currency: str | None = None,
    ):
        ranking = build_ranking(
            data,
            category=category,
            limit=1,
            start_year=start_year,
            end_year=end_year,
            municipality=municipality,
            entity_type=entity_type,
            currency=currency,
        )
        return _movers_for_ranking(ranking, limit=limit)

    @router.get("/signals")
    def signals(
        category: str = "contract_award",
        limit: int = Query(25, ge=1, le=25),
        start_year: int | None = None,
        end_year: int | None = None,
        municipality: str | None = None,
        entity_type: str | None = None,
        currency: str | None = None,
    ):
        ranking = build_ranking(
            data,
            category=category,
            limit=limit,
            start_year=start_year,
            end_year=end_year,
            municipality=municipality,
            entity_type=entity_type,
            currency=currency,
        )
        movement = _movers_for_ranking(ranking, limit=10)
        return build_signals(ranking, movement)

    @router.get("/entity/{entity_id}")
    def entity_drilldown(entity_id: str):
        return build_entity_drilldown(data, entity_id)

    return router
