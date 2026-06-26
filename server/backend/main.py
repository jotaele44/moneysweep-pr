"""
moneysweep-pr dashboard API
==============================
Thin FastAPI read layer over the frozen canonical_v1 CSVs (Tranche A). It does
NOT import the legacy pipeline — it reads data/canonical_v1/*.csv with pandas and
serves joined, dashboard-friendly JSON.

Start (from repo root):
    uvicorn server.backend.main:app --reload --port 8000

Schema reality (verified):
  * contracts reference awarding/contractor as entity_id FKs → join entities.csv
  * a contract's municipality comes from edges.csv (Entity LOCATED_IN Municipality)
  * award_amount is frequently blank → exposed as null; aggregates are null-safe
"""

from __future__ import annotations

import math
from pathlib import Path

import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

ROOT = Path(__file__).resolve().parents[2]
CANON = ROOT / "data" / "canonical_v1"

EXPECTED = {
    "contracts": [
        "contract_id",
        "awarding_entity_id",
        "contractor_entity_id",
        "award_amount",
        "status",
        "start_date",
    ],
    "entities": ["entity_id", "name", "entity_type"],
    "edges": ["edge_id", "source_node_id", "edge_type", "target_node_id"],
    "municipalities": ["municipality_id", "name", "region"],
}

app = FastAPI(title="moneysweep-pr API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

DATA: dict[str, pd.DataFrame] = {}


def _load() -> None:
    """Load canonical CSVs into cached DataFrames; fail loud on header drift."""
    for name in ["contracts", "entities", "edges", "municipalities"]:
        path = CANON / f"{name}.csv"
        if not path.exists():
            raise RuntimeError(f"missing canonical file: {path}")
        df = pd.read_csv(path, dtype=str).fillna("")
        missing = [c for c in EXPECTED[name] if c not in df.columns]
        if missing:
            raise RuntimeError(
                f"{name}.csv missing expected columns {missing}; got {list(df.columns)}"
            )
        DATA[name] = df


_load()  # eager load at import → fail fast on missing files / header drift


def _num(v):
    """Parse a possibly-blank money string → float or None (never NaN)."""
    if v is None or v == "":
        return None
    try:
        f = float(v)
        return None if math.isnan(f) else f
    except (TypeError, ValueError):
        return None


def _entity_name_map() -> dict[str, str]:
    e = DATA["entities"]
    return dict(zip(e["entity_id"], e["name"]))


def _muni_name_map() -> dict[str, str]:
    m = DATA["municipalities"]
    return dict(zip(m["municipality_id"], m["name"]))


def _located_in_map() -> dict[str, str]:
    """entity_id → municipality_id, from edges (Entity LOCATED_IN Municipality)."""
    e = DATA["edges"]
    li = e[e["edge_type"] == "LOCATED_IN"]
    return dict(zip(li["source_node_id"], li["target_node_id"]))


@app.get("/health")
def health():
    try:
        return {"status": "ok", "rows": {k: int(len(v)) for k, v in DATA.items()}}
    except Exception as exc:  # pragma: no cover
        raise HTTPException(500, str(exc))


@app.get("/contracts")
def contracts(
    municipality: str | None = None,
    agency: str | None = None,
    status: str | None = None,
    fiscal_year: int | None = None,
):
    names = _entity_name_map()
    munis = _muni_name_map()
    located = _located_in_map()
    out = []
    for _, r in DATA["contracts"].iterrows():
        awarding = names.get(r["awarding_entity_id"], r["awarding_entity_id"])
        contractor = names.get(r["contractor_entity_id"], r["contractor_entity_id"])
        muni_id = located.get(r["contractor_entity_id"]) or located.get(r["awarding_entity_id"])
        muni_name = munis.get(muni_id) if muni_id else None
        start = r.get("start_date") or ""
        fy = int(start[:4]) if start[:4].isdigit() else None
        row = {
            "contractId": r["contract_id"],
            "contractNumber": r.get("contract_number") or None,
            "awardingName": awarding or None,
            "contractorName": contractor or None,
            "municipality": muni_name,
            "serviceType": r.get("service_type") or None,
            "awardAmount": _num(r.get("award_amount")),
            "currency": r.get("currency") or None,
            "startDate": start or None,
            "endDate": r.get("end_date") or None,
            "status": r.get("status") or None,
            "confidence": _num(r.get("confidence")),
            "fiscalYear": fy,
        }
        if municipality and (row["municipality"] or "").lower() != municipality.lower():
            continue
        if agency and agency.lower() not in (row["awardingName"] or "").lower():
            continue
        if status and (row["status"] or "") != status:
            continue
        if fiscal_year and row["fiscalYear"] != fiscal_year:
            continue
        out.append(row)
    return out


@app.get("/entities")
def entities(type: str | None = None, q: str | None = None):
    df = DATA["entities"]
    out = []
    for _, r in df.iterrows():
        if type and r.get("entity_type") != type:
            continue
        if q and q.lower() not in (r.get("name") or "").lower():
            continue
        out.append(
            {
                "entityId": r["entity_id"],
                "name": r.get("name") or None,
                "entityType": r.get("entity_type") or None,
                "jurisdiction": r.get("jurisdiction") or None,
                "parentEntityId": r.get("parent_entity_id") or None,
                "confidence": _num(r.get("confidence")),
                "notes": r.get("notes") or None,
            }
        )
    return out


@app.get("/edges")
def edges(edge_type: str | None = None, source_id: str | None = None):
    names = _entity_name_map()
    munis = _muni_name_map()

    def label(node_type, node_id):
        if node_type == "Municipality":
            return munis.get(node_id, node_id)
        return names.get(node_id, node_id)

    out = []
    for _, r in DATA["edges"].iterrows():
        if edge_type and r.get("edge_type") != edge_type:
            continue
        if source_id and r.get("source_node_id") != source_id:
            continue
        out.append(
            {
                "edgeId": r["edge_id"],
                "sourceType": r.get("source_node_type"),
                "sourceId": r.get("source_node_id"),
                "sourceLabel": label(r.get("source_node_type"), r.get("source_node_id")),
                "edgeType": r.get("edge_type"),
                "targetType": r.get("target_node_type"),
                "targetId": r.get("target_node_id"),
                "targetLabel": label(r.get("target_node_type"), r.get("target_node_id")),
                "amount": _num(r.get("amount")),
                "confidence": _num(r.get("confidence")),
            }
        )
    return out


@app.get("/municipalities")
def municipalities():
    """Per-municipality contract count + null-safe summed award amount."""
    munis = _muni_name_map()
    located = _located_in_map()
    agg: dict[str, dict] = {}
    for _, r in DATA["contracts"].iterrows():
        muni_id = located.get(r["contractor_entity_id"]) or located.get(r["awarding_entity_id"])
        key = muni_id or "_unknown"
        a = agg.setdefault(
            key,
            {
                "municipalityId": muni_id,
                "name": munis.get(muni_id, "Unknown"),
                "contracts": 0,
                "total": 0.0,
                "hasAmount": False,
            },
        )
        a["contracts"] += 1
        amt = _num(r.get("award_amount"))
        if amt is not None:
            a["total"] += amt
            a["hasAmount"] = True
    rows = []
    for a in agg.values():
        rows.append({**a, "total": a["total"] if a["hasAmount"] else None})
    rows.sort(key=lambda x: x["contracts"], reverse=True)
    return rows


@app.get("/stats")
def stats():
    c = DATA["contracts"]
    by_status: dict[str, int] = {}
    by_service: dict[str, int] = {}
    amounts = 0
    for _, r in c.iterrows():
        by_status[r.get("status") or "unknown"] = by_status.get(r.get("status") or "unknown", 0) + 1
        st = r.get("service_type") or "unspecified"
        by_service[st] = by_service.get(st, 0) + 1
        if _num(r.get("award_amount")) is not None:
            amounts += 1
    ent_types: dict[str, int] = {}
    for _, r in DATA["entities"].iterrows():
        t = r.get("entity_type") or "unknown"
        ent_types[t] = ent_types.get(t, 0) + 1
    return {
        "contracts": int(len(c)),
        "entities": int(len(DATA["entities"])),
        "edges": int(len(DATA["edges"])),
        "municipalities": int(len(DATA["municipalities"])),
        "contractsWithAmount": amounts,
        "byStatus": by_status,
        "byServiceType": by_service,
        "byEntityType": ent_types,
    }
