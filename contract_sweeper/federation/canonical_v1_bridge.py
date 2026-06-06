"""Bridge canonical_v1 -> the federation export model (WS-Q).

Maps the committed ``data/canonical_v1`` node/edge/evidence tables into the three
federation JSONL streams that validate against the stable schemas in
``schemas/contract_sweeper_{source,entity,relationship}.schema.json``:

* **sources.jsonl**       — one row per canonical_v1 evidence row (``src_<32hex>``).
* **entities.jsonl**      — canonical_v1 ``entities`` + ``people`` (``ent_<32hex>``),
                            carrying the canonical_v1 id in ``external_ids``.
* **relationships.jsonl** — canonical_v1 ``edges`` whose *both* endpoints map to a
                            federation entity (Person/Entity) (``rel_<32hex>``).

Edges touching non-entity nodes (Contract/Debt/Project/FundingSource/Property/
Municipality/LobbyingRecord) are reported as ``not_yet_federated`` rather than
forced into the entity-only relationship schema. Every row carries a ``lineage``
object and ``synthetic=false``. Stdlib only; deterministic and idempotent.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from contract_sweeper.runtime.canonical_ids import (
    fed_entity_id,
    fed_relationship_id,
    fed_source_id,
)
from contract_sweeper.validation.canonical_v1_schema import load_all_tables

REPO_ROOT = Path(__file__).resolve().parents[2]
PRODUCER = "contract_sweeper/federation/canonical_v1_bridge.py"
PHASE = "CANONICAL_V1_FEDERATION_BRIDGE"

# canonical_v1 edge endpoint node types that become federation entities.
_ENTITY_NODE_TYPES = {"Person", "Entity"}

# canonical_v1 entity_type -> federation entity_type vocabulary.
_ENTITY_TYPE_MAP = {
    "agency": "funding_agency",
    "utility": "recipient",
    "firm": "recipient",
    "fund": "recipient",
    "nonprofit": "recipient",
    "other": "recipient",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _lineage(source_csv: str) -> dict[str, Any]:
    return {
        "producer_script": PRODUCER,
        "producer_phase": PHASE,
        "source_inputs": [source_csv],
        "extraction_method": "canonical_v1_bridge",
    }


def _norm_conf(value: str) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def build_streams(root: Path | None = None) -> dict[str, Any]:
    """Return the three federation streams + a coverage report (no writing)."""
    root = root or REPO_ROOT
    tables = load_all_tables(root)
    now = _now()

    # --- sources from evidence ---
    sources: list[dict[str, Any]] = []
    evidence_to_src: dict[str, str] = {}
    for ev in tables.get("evidence", []):
        ceid = (ev.get("evidence_id") or "").strip()
        if not ceid:
            continue
        sid = fed_source_id(ceid)
        evidence_to_src[ceid] = sid
        sources.append({
            "source_id": sid,
            "source_type": (ev.get("source_type") or "other").strip() or "other",
            "source_name": (ev.get("source_name") or "").strip(),
            "source_ref": ceid,
            "confidence": _norm_conf(ev.get("confidence")),
            "lineage": _lineage("data/canonical_v1/evidence.csv"),
            "synthetic": False,
            "created_at": now,
            "extracted_at": now,
        })

    # --- entities from canonical_v1 entities + people ---
    entities: list[dict[str, Any]] = []
    node_to_ent: dict[str, str] = {}

    def _emit_entity(cid: str, name: str, normalized: str, etype: str,
                     jurisdiction: str, ev_id: str, conf: str, source_csv: str) -> None:
        eid = fed_entity_id(cid)
        node_to_ent[cid] = eid
        entities.append({
            "entity_id": eid,
            "source_id": evidence_to_src.get(ev_id, fed_source_id(ev_id)),
            "name": name,
            "normalized_name": normalized or name.upper(),
            "entity_type": etype,
            "jurisdiction": jurisdiction or "PR",
            "external_ids": {"canonical_v1_id": cid},
            "confidence": _norm_conf(conf),
            "lineage": _lineage(source_csv),
            "synthetic": False,
            "created_at": now,
            "extracted_at": now,
        })

    for ent in tables.get("entities", []):
        cid = (ent.get("entity_id") or "").strip()
        if not cid:
            continue
        _emit_entity(cid, (ent.get("name") or "").strip(),
                     (ent.get("normalized_name") or "").strip(),
                     _ENTITY_TYPE_MAP.get((ent.get("entity_type") or "").strip(), "recipient"),
                     (ent.get("jurisdiction") or "").strip(),
                     (ent.get("evidence_id") or "").strip(),
                     ent.get("confidence"), "data/canonical_v1/entities.csv")
    for per in tables.get("people", []):
        cid = (per.get("person_id") or "").strip()
        if not cid:
            continue
        _emit_entity(cid, (per.get("full_name") or "").strip(),
                     (per.get("normalized_name") or "").strip(), "person",
                     (per.get("jurisdiction") or "").strip(),
                     (per.get("evidence_id") or "").strip(),
                     per.get("confidence"), "data/canonical_v1/people.csv")

    # --- relationships from edges with entity endpoints ---
    relationships: list[dict[str, Any]] = []
    not_yet: list[dict[str, str]] = []
    for e in tables.get("edges", []):
        s_type = (e.get("source_node_type") or "").strip()
        t_type = (e.get("target_node_type") or "").strip()
        sid = (e.get("source_node_id") or "").strip()
        tid = (e.get("target_node_id") or "").strip()
        etype = (e.get("edge_type") or "").strip()
        ceid = (e.get("evidence_id") or "").strip()
        if s_type in _ENTITY_NODE_TYPES and t_type in _ENTITY_NODE_TYPES \
                and sid in node_to_ent and tid in node_to_ent:
            relationships.append({
                "relationship_id": fed_relationship_id(sid, etype, tid),
                "source_id": evidence_to_src.get(ceid, fed_source_id(ceid)),
                "source_entity_id": node_to_ent[sid],
                "target_entity_id": node_to_ent[tid],
                "relationship_type": etype,
                "evidence_source_id": evidence_to_src.get(ceid, fed_source_id(ceid)),
                "confidence": _norm_conf(e.get("confidence")),
                "lineage": _lineage("data/canonical_v1/edges.csv"),
                "synthetic": False,
                "created_at": now,
                "extracted_at": now,
            })
        else:
            not_yet.append({"edge_id": (e.get("edge_id") or "").strip(),
                            "edge_type": etype,
                            "reason": f"non-entity endpoint ({s_type}->{t_type})"})

    return {
        "sources": sources,
        "entities": entities,
        "relationships": relationships,
        "not_yet_federated": not_yet,
    }
