"""Build the top-form Graph Export (Gate ``graph_export``).

Projects the committed master registries into a property-graph: a node table
(organizations, government agencies, municipalities, and people) and an edge
table (parent/instrumentality and operator relationships, lobbying
registrations, and board memberships). Every edge carries ``evidence_tier`` and
``confidence`` and references node ids that exist in the node table, so the
export is referentially closed.

Inputs (all committed, deterministic, no network):

* ``data/reference/entity_master.csv``      — 26 organizations + agencies
* ``data/reference/agency_master.csv``       — the 78 ``ENT_MUNI_`` municipios
* ``data/reference/person_master.csv``       — 60 people
* ``data/reference/entity_parent_map.csv``   — parent/operator edges (master ids)
* ``data/canonical_v1/lobbying_records.csv`` — lobbying registrations (canonical ids)
* ``data/canonical_v1/roles.csv``            — board/role memberships (canonical ids)

Canonical_v1 ids (``entity_<hash>`` / ``person_<hash>``) share their hash suffix
with the master ids (``ENT_*_<hash>`` / ``ENT_PERSON_<hash>``), so a
``suffix -> node_id`` index resolves them deterministically.

Outputs:

* ``exports/graph/nodes.csv`` / ``edges.csv``             — analyst-friendly tables
* ``exports/graph/neo4j_nodes.csv`` / ``neo4j_edges.csv`` — ``neo4j-admin import`` headers
* ``data/manifests/graph_export.json``                    — provenance manifest

Reuses ``name_hash`` and the stdlib schema validator (no ``jsonschema`` dep).

CLI::

    python scripts/build_graph_export.py            # write the exports + manifest
    python scripts/build_graph_export.py --check     # validate without writing
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from contract_sweeper.runtime.canonical_ids import name_hash
from contract_sweeper.validation.canonical_v1_schema import validate_row

REPO_ROOT = Path(__file__).resolve().parents[1]

ENTITY_MASTER = "data/reference/entity_master.csv"
AGENCY_MASTER = "data/reference/agency_master.csv"
PERSON_MASTER = "data/reference/person_master.csv"
PARENT_MAP = "data/reference/entity_parent_map.csv"
LOBBYING = "data/canonical_v1/lobbying_records.csv"
ROLES = "data/canonical_v1/roles.csv"

NODES_OUT = "exports/graph/nodes.csv"
EDGES_OUT = "exports/graph/edges.csv"
NEO4J_NODES_OUT = "exports/graph/neo4j_nodes.csv"
NEO4J_EDGES_OUT = "exports/graph/neo4j_edges.csv"
MANIFEST_OUT = "data/manifests/graph_export.json"

NODE_SCHEMA = "schemas/graph_nodes.schema.json"
EDGE_SCHEMA = "schemas/graph_edges.schema.json"

NODE_COLUMNS = [
    "node_id", "node_type", "canonical_name", "jurisdiction",
    "source_id", "evidence_tier", "confidence", "notes",
]
EDGE_COLUMNS = [
    "edge_id", "from_node_id", "to_node_id", "edge_type",
    "source_id", "evidence_tier", "confidence", "notes",
]

# entity_master.entity_type already matches the node_type vocabulary.
MUNI_NODE_TYPE = "municipality"
PERSON_NODE_TYPE = "person"

# entity_parent_map.relationship_type -> graph edge_type. Operator relationships
# have no dedicated controlled verb, so they map to the generic RELATED_TO and
# preserve the precise relationship in the edge note (asserting OWNS/PARENT_OF of
# an operator would be false — the Commonwealth, not the operator, owns the asset).
PARENT_EDGE_TYPE = {
    "INSTRUMENTALITY_OF": "PARENT_OF",
    "SUBSIDIARY_OF": "PARENT_OF",
    "P3_OPERATOR_OF": "RELATED_TO",
    "CONCESSION_OPERATOR_OF": "RELATED_TO",
}


def _load_schema(root: Path, rel: str) -> dict[str, Any]:
    return json.loads((root / rel).read_text(encoding="utf-8"))


def _read(root: Path, rel: str) -> list[dict[str, str]]:
    with (root / rel).open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _suffix(identifier: str) -> str:
    """The trailing hash that master and canonical_v1 ids share."""
    return identifier.rsplit("_", 1)[-1]


def build_nodes(root: Path | None = None) -> list[dict[str, Any]]:
    """Return the unified node table: entities + municipios + people."""
    root = root or REPO_ROOT
    nodes: list[dict[str, Any]] = []
    seen: set[str] = set()

    for r in _read(root, ENTITY_MASTER):
        nid = r["entity_id"]
        seen.add(nid)
        nodes.append({
            "node_id": nid,
            "node_type": r["entity_type"],
            "canonical_name": r["canonical_name"],
            "jurisdiction": r["jurisdiction"],
            "source_id": r["source_id"],
            "evidence_tier": r["evidence_tier"],
            "confidence": float(r["confidence"]),
            "notes": "",
        })

    # Only the municipios from agency_master; its agencies duplicate entity_master.
    for r in _read(root, AGENCY_MASTER):
        nid = r["agency_id"]
        if not nid.startswith("ENT_MUNI_") or nid in seen:
            continue
        seen.add(nid)
        nodes.append({
            "node_id": nid,
            "node_type": MUNI_NODE_TYPE,
            "canonical_name": r["canonical_name"],
            "jurisdiction": r["jurisdiction"],
            "source_id": r["source_id"],
            "evidence_tier": r["evidence_tier"],
            "confidence": float(r["confidence"]),
            "notes": (r.get("notes") or "").strip(),
        })

    for r in _read(root, PERSON_MASTER):
        nid = r["person_id"]
        if nid in seen:
            continue
        seen.add(nid)
        nodes.append({
            "node_id": nid,
            "node_type": PERSON_NODE_TYPE,
            "canonical_name": r["canonical_name"],
            "jurisdiction": r["jurisdiction"],
            "source_id": r["source_id"],
            "evidence_tier": r["evidence_tier"],
            "confidence": float(r["confidence"]),
            "notes": "",
        })

    return nodes


def _edge(from_id: str, to_id: str, edge_type: str, source_id: str,
          evidence_tier: str, confidence: float, notes: str) -> dict[str, Any]:
    return {
        "edge_id": f"EDGE_{name_hash(from_id + '|' + to_id + '|' + edge_type)}",
        "from_node_id": from_id,
        "to_node_id": to_id,
        "edge_type": edge_type,
        "source_id": source_id,
        "evidence_tier": evidence_tier,
        "confidence": confidence,
        "notes": notes,
    }


def build_edges(root: Path | None = None,
                node_ids: set[str] | None = None) -> list[dict[str, Any]]:
    """Return the edge table; every endpoint resolves to a node id."""
    root = root or REPO_ROOT
    if node_ids is None:
        node_ids = {n["node_id"] for n in build_nodes(root)}
    by_suffix = {_suffix(nid): nid for nid in node_ids}
    edges: list[dict[str, Any]] = []

    # Parent/instrumentality + operator relationships (already master ids).
    for r in _read(root, PARENT_MAP):
        rel = r["relationship_type"]
        edge_type = PARENT_EDGE_TYPE.get(rel, "RELATED_TO")
        note = r.get("notes") or ""
        if rel not in ("INSTRUMENTALITY_OF", "SUBSIDIARY_OF"):
            note = f"{rel}: {note}".strip(": ")
        edges.append(_edge(
            r["parent_entity_id"], r["child_entity_id"], edge_type,
            "entity_parent_map", r["evidence_tier"], float(r["confidence"]), note,
        ))

    # Lobbying registrations: lobbyist -> client (canonical ids -> node ids).
    for r in _read(root, LOBBYING):
        frm = by_suffix.get(_suffix(r["lobbyist_entity_id"]))
        to = by_suffix.get(_suffix(r["client_entity_id"]))
        if not frm or not to:
            continue
        edges.append(_edge(
            frm, to, "REGISTERED_LOBBYING_FOR", "canonical_v1_lobbying_records",
            "T3", float(r.get("confidence") or 0.0), (r.get("notes") or "").strip(),
        ))

    # Board / role memberships: person -> entity (canonical ids -> node ids).
    for r in _read(root, ROLES):
        frm = by_suffix.get(_suffix(r["person_id"]))
        to = by_suffix.get(_suffix(r["entity_id"]))
        if not frm or not to:
            continue
        title = (r.get("role_title") or "").strip()
        edges.append(_edge(
            frm, to, "BOARD_MEMBER_OF", "canonical_v1_roles",
            "T2", float(r.get("confidence") or 0.0), title,
        ))

    return edges


def check(nodes: list[dict[str, Any]], edges: list[dict[str, Any]],
          root: Path | None = None) -> list[str]:
    """Return a list of problems (empty == valid)."""
    root = root or REPO_ROOT
    problems: list[str] = []

    if not nodes:
        problems.append("no graph nodes produced")
    if not edges:
        problems.append("no graph edges produced")

    node_ids = [n["node_id"] for n in nodes]
    if len(set(node_ids)) != len(node_ids):
        problems.append("duplicate node_id values present")
    edge_ids = [e["edge_id"] for e in edges]
    if len(set(edge_ids)) != len(edge_ids):
        problems.append("duplicate edge_id values present")

    node_schema = _load_schema(root, NODE_SCHEMA)
    for i, node in enumerate(nodes, start=1):
        for msg in validate_row(node, node_schema):
            problems.append(f"node {i} ({node.get('node_id')}): {msg}")

    edge_schema = _load_schema(root, EDGE_SCHEMA)
    known = set(node_ids)
    for i, edge in enumerate(edges, start=1):
        for msg in validate_row(edge, edge_schema):
            problems.append(f"edge {i} ({edge.get('edge_id')}): {msg}")
        # Node-existence integrity: both endpoints must be nodes.
        if edge["from_node_id"] not in known:
            problems.append(f"edge {i}: from_node_id {edge['from_node_id']} not in nodes")
        if edge["to_node_id"] not in known:
            problems.append(f"edge {i}: to_node_id {edge['to_node_id']} not in nodes")
        # Evidence gate: every edge carries tier + confidence.
        if not edge.get("evidence_tier"):
            problems.append(f"edge {i}: missing evidence_tier")
        if edge.get("confidence") in (None, ""):
            problems.append(f"edge {i}: missing confidence")

    return problems


def _write_csv(rows: list[dict[str, Any]], columns: list[str], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _write_neo4j_nodes(nodes: list[dict[str, Any]], out_path: Path) -> None:
    """Typed-header node file for ``neo4j-admin database import``."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    header = ["node_id:ID", ":LABEL", "canonical_name", "jurisdiction",
              "source_id", "evidence_tier", "confidence:float", "notes"]
    with out_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(header)
        for n in nodes:
            writer.writerow([
                n["node_id"], n["node_type"], n["canonical_name"], n["jurisdiction"],
                n["source_id"], n["evidence_tier"], n["confidence"], n["notes"],
            ])


def _write_neo4j_edges(edges: list[dict[str, Any]], out_path: Path) -> None:
    """Typed-header relationship file for ``neo4j-admin database import``."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    header = [":START_ID", ":END_ID", ":TYPE", "edge_id",
              "source_id", "evidence_tier", "confidence:float", "notes"]
    with out_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(header)
        for e in edges:
            writer.writerow([
                e["from_node_id"], e["to_node_id"], e["edge_type"], e["edge_id"],
                e["source_id"], e["evidence_tier"], e["confidence"], e["notes"],
            ])


def build(root: Path | None = None) -> dict[str, Any]:
    """Build, validate, and write the graph export + manifest."""
    root = root or REPO_ROOT
    nodes = build_nodes(root)
    edges = build_edges(root, {n["node_id"] for n in nodes})
    problems = check(nodes, edges, root)
    if problems:
        raise ValueError("graph_export check failed: " + "; ".join(problems))

    _write_csv(nodes, NODE_COLUMNS, root / NODES_OUT)
    _write_csv(edges, EDGE_COLUMNS, root / EDGES_OUT)
    _write_neo4j_nodes(nodes, root / NEO4J_NODES_OUT)
    _write_neo4j_edges(edges, root / NEO4J_EDGES_OUT)

    manifest = {
        "producer_script": "scripts/build_graph_export.py",
        "producer_phase": "TOP_FORM_GRAPH_EXPORT",
        "node_schema": NODE_SCHEMA,
        "edge_schema": EDGE_SCHEMA,
        "source_inputs": [
            ENTITY_MASTER, AGENCY_MASTER, PERSON_MASTER,
            PARENT_MAP, LOBBYING, ROLES,
        ],
        "outputs": [NODES_OUT, EDGES_OUT, NEO4J_NODES_OUT, NEO4J_EDGES_OUT],
        "node_count": len(nodes),
        "edge_count": len(edges),
        "node_types": sorted({n["node_type"] for n in nodes}),
        "edge_types": sorted({e["edge_type"] for e in edges}),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    manifest_path = root / MANIFEST_OUT
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the top-form Graph Export.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--check", action="store_true", help="Validate without writing.")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    if args.check:
        nodes = build_nodes(root)
        edges = build_edges(root, {n["node_id"] for n in nodes})
        problems = check(nodes, edges, root)
        print(json.dumps({
            "ok": not problems,
            "node_count": len(nodes),
            "edge_count": len(edges),
            "problems": problems,
        }, indent=2))
        return 0 if not problems else 1
    print(json.dumps(build(root), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
