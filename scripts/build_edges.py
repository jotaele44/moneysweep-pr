"""Build Canonical v1 ``edges.csv`` from a source-backed relationships file (WS-M).

This is the generic, evidence-first edge producer. It reads a relationships
source (human-named, claim-bearing rows), resolves each endpoint name to an
existing canonical node id, and emits typed edges only when:

* the ``edge_type`` is in the controlled vocabulary (the 12 approved verbs),
* both endpoints resolve to existing nodes (``no broken reference``), and
* the edge is backed by an ``evidence.csv`` row (``no provenance -> no edge``).

Unresolved or uncontrolled rows are reported and skipped (never written as
edges), so the committed graph stays clean. Edge ids are deterministic from the
(source, verb, target) triple, so re-runs are idempotent.

Roadmap: WS-M, tasks T177-T194 (LOCATED_IN seed first). Stdlib only.

CLI::

    python scripts/build_edges.py            # build edges from the seed
    python scripts/build_edges.py --check     # resolve + report without writing
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

from contract_sweeper.runtime.canonical_ids import edge_id
from contract_sweeper.runtime.name_normalization import normalize_name, normalize_person_name
from contract_sweeper.validation.canonical_v1_schema import EDGE_TYPES, NODE_TYPE_TABLE
from scripts.build_evidence import Evidence, make_evidence, merge_evidence

REPO_ROOT = Path(__file__).resolve().parents[1]
RELATIONSHIPS = "data/reference/canonical_v1_relationships_seed.csv"
EDGES_OUT = "data/canonical_v1/edges.csv"
EVIDENCE_OUT = "data/canonical_v1/evidence.csv"
ROLES_IN = "data/canonical_v1/roles.csv"
DEBT_IN = "data/canonical_v1/debt_instruments.csv"
PROJECTS_IN = "data/canonical_v1/projects.csv"
DATA_DIR = "data/canonical_v1"
MANIFEST_OUT = "data/manifests/canonical_v1/edges.json"
SOURCE_NAME = "PR Public-Money Relationships (reference seed)"

EDGE_COLUMNS = [
    "edge_id", "source_node_type", "source_node_id", "edge_type",
    "target_node_type", "target_node_id", "start_date", "end_date",
    "amount", "currency", "confidence", "evidence_id", "notes",
]

# node type -> (csv, id column, display-name column, aliases column, person?)
_NODE_LOOKUP = {
    "Person": ("people.csv", "person_id", "full_name", "aliases", True),
    "Entity": ("entities.csv", "entity_id", "name", None, False),  # aliases live in notes
    "Municipality": ("municipalities.csv", "municipality_id", "name", "aliases", False),
}


def _norm(name: str, person: bool) -> str:
    return normalize_person_name(name) if person else normalize_name(name)


def build_resolver(root: Path) -> dict[str, dict[str, str]]:
    """Build per-node-type maps of normalized name/alias -> node id."""
    resolver: dict[str, dict[str, str]] = {}
    for ntype, (csv_name, id_col, name_col, alias_col, person) in _NODE_LOOKUP.items():
        index: dict[str, str] = {}
        path = root / DATA_DIR / csv_name
        if not path.exists():
            resolver[ntype] = index
            continue
        with path.open(newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                nid = (row.get(id_col) or "").strip()
                if not nid:
                    continue
                names = [row.get(name_col, "")]
                if alias_col and row.get(alias_col):
                    names.extend(row[alias_col].split("|"))
                # entities keep aliases inside notes as "aliases=A|B|C"
                notes = row.get("notes", "") or ""
                if notes.startswith("aliases="):
                    names.extend(notes[len("aliases="):].split("|"))
                for n in names:
                    key = _norm(n, person)
                    if key:
                        index.setdefault(key, nid)
        resolver[ntype] = index
    return resolver


def resolve(resolver: dict[str, dict[str, str]], ntype: str, name: str) -> str | None:
    person = _NODE_LOOKUP.get(ntype, (None,) * 5)[4]
    return resolver.get(ntype, {}).get(_norm(name, bool(person)))


def build_edges(root: Path | None = None) -> dict[str, Any]:
    """Resolve the relationships seed into edges + evidence + skip report."""
    root = root or REPO_ROOT
    resolver = build_resolver(root)
    edge_rows: list[dict[str, Any]] = []
    evidence_rows: list[Evidence] = []
    skipped: list[dict[str, str]] = []
    seen: set[str] = set()

    with (root / RELATIONSHIPS).open(newline="", encoding="utf-8") as fh:
        for i, rel in enumerate(csv.DictReader(fh), start=2):
            etype = (rel.get("edge_type") or "").strip()
            s_type = (rel.get("source_node_type") or "").strip()
            t_type = (rel.get("target_node_type") or "").strip()
            s_name = (rel.get("source_name") or "").strip()
            t_name = (rel.get("target_name") or "").strip()
            reason = None
            if etype not in EDGE_TYPES:
                reason = f"uncontrolled edge_type {etype!r}"
            elif s_type not in NODE_TYPE_TABLE or t_type not in NODE_TYPE_TABLE:
                reason = "unknown node type"
            sid = resolve(resolver, s_type, s_name) if not reason else None
            tid = resolve(resolver, t_type, t_name) if not reason else None
            if not reason and sid is None:
                reason = f"unresolved source {s_type}:{s_name!r}"
            if not reason and tid is None:
                reason = f"unresolved target {t_type}:{t_name!r}"
            if reason:
                skipped.append({"row": str(i), "reason": reason})
                continue

            ev = make_evidence(
                source_type=(rel.get("source_type") or "web").strip(),
                source_name=SOURCE_NAME,
                source_path_or_url=RELATIONSHIPS,
                page_or_line_ref=f"row {i}",
                claim=(rel.get("claim") or f"{s_name} {etype} {t_name}").strip(),
                extraction_method=(rel.get("extraction_method") or "manual").strip(),
                evidence_tier=(rel.get("evidence_tier") or "").strip() or None,
                review_status="accepted",
            )
            evidence_rows.append(ev)
            eid = edge_id(sid, etype, tid)
            if eid in seen:
                continue
            seen.add(eid)
            edge_rows.append({
                "edge_id": eid,
                "source_node_type": s_type,
                "source_node_id": sid,
                "edge_type": etype,
                "target_node_type": t_type,
                "target_node_id": tid,
                "start_date": (rel.get("start_date") or "").strip(),
                "end_date": (rel.get("end_date") or "").strip(),
                "amount": (rel.get("amount") or "").strip(),
                "currency": (rel.get("currency") or "").strip(),
                "confidence": ev.confidence,
                "evidence_id": ev.evidence_id,
                "notes": "",
            })

    # Derive HOLDS_ROLE_IN edges from roles.csv (single-writer: edges.csv is only
    # written here). Each role row already carries a resolved person_id, entity_id,
    # and an accepted evidence_id, so the role edge reuses that provenance.
    for role in _read_roles(root):
        pid = (role.get("person_id") or "").strip()
        eid_entity = (role.get("entity_id") or "").strip()
        ev_id = (role.get("evidence_id") or "").strip()
        if not (pid and eid_entity and ev_id):
            continue
        eid = edge_id(pid, "HOLDS_ROLE_IN", eid_entity)
        if eid in seen:
            continue
        seen.add(eid)
        edge_rows.append({
            "edge_id": eid,
            "source_node_type": "Person",
            "source_node_id": pid,
            "edge_type": "HOLDS_ROLE_IN",
            "target_node_type": "Entity",
            "target_node_id": eid_entity,
            "start_date": (role.get("start_date") or "").strip(),
            "end_date": (role.get("end_date") or "").strip(),
            "amount": "",
            "currency": "",
            "confidence": (role.get("confidence") or "").strip(),
            "evidence_id": ev_id,
            "notes": (role.get("role_title") or "").strip(),
        })

    # Derive HOLDS_DEBT edges from debt_instruments.csv: the issuer entity holds
    # (issues) the instrument. The issuer name is carried in the debt row notes as
    # "...; issuer=<name>"; resolve it to an existing entity. Edges are emitted
    # only when the issuer resolves (no broken reference); unresolved issuers are
    # reported so they can be added as entities later.
    for debt in _read_debt(root):
        did = (debt.get("debt_id") or "").strip()
        ev_id = (debt.get("evidence_id") or "").strip()
        issuer_eid = (debt.get("issuer_entity_id") or "").strip()
        if not (did and ev_id and issuer_eid):
            continue
        eid = edge_id(issuer_eid, "HOLDS_DEBT", did)
        if eid in seen:
            continue
        seen.add(eid)
        edge_rows.append({
            "edge_id": eid,
            "source_node_type": "Entity",
            "source_node_id": issuer_eid,
            "edge_type": "HOLDS_DEBT",
            "target_node_type": "DebtInstrument",
            "target_node_id": did,
            "start_date": "",
            "end_date": (debt.get("maturity_date") or "").strip(),
            "amount": (debt.get("par_amount") or "").strip(),
            "currency": (debt.get("currency") or "").strip(),
            "confidence": (debt.get("confidence") or "").strip(),
            "evidence_id": ev_id,
            "notes": (debt.get("debt_class") or "").strip(),
        })

    # Derive LOCATED_IN edges from projects.csv: a project located in a
    # municipality. The project row already carries a resolved municipality_id and
    # an accepted evidence_id, so the edge reuses that provenance.
    for proj in _read_projects(root):
        pid = (proj.get("project_id") or "").strip()
        muni_id = (proj.get("municipality_id") or "").strip()
        ev_id = (proj.get("evidence_id") or "").strip()
        if not (pid and muni_id and ev_id):
            continue
        eid = edge_id(pid, "LOCATED_IN", muni_id)
        if eid in seen:
            continue
        seen.add(eid)
        edge_rows.append({
            "edge_id": eid,
            "source_node_type": "Project",
            "source_node_id": pid,
            "edge_type": "LOCATED_IN",
            "target_node_type": "Municipality",
            "target_node_id": muni_id,
            "start_date": "",
            "end_date": "",
            "amount": "",
            "currency": "",
            "confidence": (proj.get("confidence") or "").strip(),
            "evidence_id": ev_id,
            "notes": (proj.get("project_type") or "").strip(),
        })

    return {"edge_rows": edge_rows, "evidence_rows": evidence_rows, "skipped": skipped}


def _read_projects(root: Path) -> list[dict[str, str]]:
    """Read projects.csv rows (empty list if the table is missing or header-only)."""
    path = root / PROJECTS_IN
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as fh:
        return [r for r in csv.DictReader(fh) if (r.get("project_id") or "").strip()]


def _read_roles(root: Path) -> list[dict[str, str]]:
    """Read roles.csv rows (empty list if the table is missing or header-only)."""
    path = root / ROLES_IN
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as fh:
        return [r for r in csv.DictReader(fh) if (r.get("role_id") or "").strip()]


def _read_debt(root: Path) -> list[dict[str, str]]:
    """Read debt_instruments.csv rows (empty list if missing or header-only)."""
    path = root / DEBT_IN
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as fh:
        return [r for r in csv.DictReader(fh) if (r.get("debt_id") or "").strip()]




def _write(rows: list[dict[str, Any]], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=EDGE_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def ingest(root: Path | None = None) -> dict[str, Any]:
    root = root or REPO_ROOT
    built = build_edges(root)
    _write(built["edge_rows"], root / EDGES_OUT)
    evidence_manifest = merge_evidence(root / EVIDENCE_OUT, built["evidence_rows"])
    by_type: dict[str, int] = {}
    for e in built["edge_rows"]:
        by_type[e["edge_type"]] = by_type.get(e["edge_type"], 0) + 1
    manifest = {
        "producer_script": "scripts/build_edges.py",
        "producer_phase": "CANONICAL_V1_EDGES_BUILD",
        "source_inputs": [RELATIONSHIPS],
        "edge_count": len(built["edge_rows"]),
        "edge_types": by_type,
        "skipped_count": len(built["skipped"]),
        "skipped": built["skipped"],
        "evidence_table_rows": evidence_manifest["row_count"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    manifest_path = root / MANIFEST_OUT
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build canonical_v1 edges from the relationships seed.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    if args.check:
        built = build_edges(root)
        print(json.dumps({"edge_count": len(built["edge_rows"]),
                          "skipped": built["skipped"]}, indent=2))
        return 0
    print(json.dumps(ingest(root), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
