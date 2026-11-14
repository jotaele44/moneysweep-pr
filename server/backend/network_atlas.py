"""Bounded read-only Network Atlas v1 adapter over legacy canonical CSV rows.

Legacy edges have no adjudicated provenance; NEVER present them as verified.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

router = APIRouter(prefix="/network-atlas/v1", tags=["Network Atlas"])


def build_neighborhood(data, entity_id: str, limit: int = 100):
    if not 1 <= limit <= 200:
        raise ValueError("limit outside [1, 200]")
    entities = data["entities"]
    edges = data["edges"]
    known = set(entities["entity_id"].astype(str))
    if entity_id not in known:
        raise KeyError(entity_id)
    nodes = {entity_id}
    items = []
    truncated = False
    for _, row in edges.iterrows():
        source = str(row["source_node_id"])
        target = str(row["target_node_id"])
        if source != entity_id and target != entity_id:
            continue
        if len(items) >= limit:
            truncated = True
            break
        if source not in known or target not in known:
            continue  # dangling endpoint is never silently minted
        nodes.update((source, target))
        items.append({
            "edgeId": str(row["edge_id"]),
            "sourceId": source,
            "targetId": target,
            "predicate": str(row["edge_type"]),
            "adjudication": "UNVERIFIED",
            "evidence": [],
        })
    names = dict(zip(entities["entity_id"].astype(str), entities["name"].astype(str)))
    return {
        "schemaVersion": "network-atlas/1.0",
        "focusId": entity_id,
        "depth": 1,
        "nodes": [{"entityId": key, "label": names[key]} for key in sorted(nodes)],
        "edges": items,
        "truncated": truncated,
        "coverage": "LEGACY_UNVERIFIED",
    }


def attach_data(data):
    """Bind existing backend DATA at request execution without copying source facts."""
    @router.get("/neighborhood")
    def neighborhood(entity_id: str = Query(min_length=1, max_length=256),
                     limit: int = Query(default=100, ge=1, le=200),
                     depth: int = Query(default=1, ge=1, le=1)):
        try:
            return build_neighborhood(data, entity_id, limit)
        except KeyError:
            raise HTTPException(status_code=404, detail="Unknown canonical entity ID")
    return router
