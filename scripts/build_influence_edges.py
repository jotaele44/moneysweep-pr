"""Build the top-form Influence Edges (Gate ``influence``, item ``influence_edge_schema``).

Locks ``schemas/influence_edges.schema.json`` into a deterministic producer: a
single normalized influence-edge table assembled from the committed canonical
relationships — lobbying registrations, board/role memberships, and
parent/operator control — with each endpoint resolved to a master entity_id and
typed against the master registries.

Inputs (committed, deterministic, no network):

* ``data/canonical_v1/lobbying_records.csv`` — lobbyist -> client (LOBBIES_FOR)
* ``data/canonical_v1/roles.csv``            — person -> entity (BOARD_MEMBER_OF)
* ``data/reference/entity_parent_map.csv``   — child -> parent (SUBSIDIARY_OF / OWNS_OR_CONTROLS)
* ``data/reference/{entity,agency,person}_master.csv`` — id -> entity_type index

Canonical_v1 ids (``entity_<hash>`` / ``person_<hash>``) share their hash suffix
with the master ids, so a ``suffix -> master_id`` index resolves them.

Output: ``data/reference/influence_edges.csv`` + ``data/manifests/influence_edges.json``.

Reuses ``name_hash`` and the stdlib schema validator (no ``jsonschema`` dep).

CLI::

    python scripts/build_influence_edges.py            # write the CSV + manifest
    python scripts/build_influence_edges.py --check     # validate without writing
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

OUT = "data/reference/influence_edges.csv"
MANIFEST_OUT = "data/manifests/influence_edges.json"
SCHEMA = "schemas/influence_edges.schema.json"

COLUMNS = [
    "edge_id",
    "source_id",
    "source_type",
    "from_entity_id",
    "from_entity_type",
    "to_entity_id",
    "to_entity_type",
    "relationship_type",
    "relationship_subtype",
    "filing_year",
    "jurisdiction",
    "evidence_tier",
    "confidence",
    "notes",
]

# entity_parent_map.relationship_type -> influence relationship_type + direction.
# SUBSIDIARY_OF points child -> parent; OWNS_OR_CONTROLS points operator -> asset.
PARENT_INFLUENCE = {
    "INSTRUMENTALITY_OF": ("SUBSIDIARY_OF", "child_to_parent"),
    "SUBSIDIARY_OF": ("SUBSIDIARY_OF", "child_to_parent"),
    "P3_OPERATOR_OF": ("OWNS_OR_CONTROLS", "child_to_parent"),
    "CONCESSION_OPERATOR_OF": ("OWNS_OR_CONTROLS", "child_to_parent"),
}


def _load_schema(root: Path) -> dict[str, Any]:
    return json.loads((root / SCHEMA).read_text(encoding="utf-8"))


def _read(root: Path, rel: str) -> list[dict[str, str]]:
    with (root / rel).open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _suffix(identifier: str) -> str:
    return identifier.rsplit("_", 1)[-1]


def _type_index(root: Path) -> dict[str, str]:
    """Map every master id -> its entity_type (organization/government_agency/
    municipality/person)."""
    index: dict[str, str] = {}
    for r in _read(root, ENTITY_MASTER):
        index[r["entity_id"]] = r["entity_type"]
    for r in _read(root, AGENCY_MASTER):
        if r["agency_id"].startswith("ENT_MUNI_"):
            index.setdefault(r["agency_id"], "municipality")
    for r in _read(root, PERSON_MASTER):
        index.setdefault(r["person_id"], "person")
    return index


def _edge(
    source_id: str,
    source_type: str,
    from_id: str,
    from_type: str,
    to_id: str,
    to_type: str,
    rel: str,
    subtype: str,
    filing_year: str,
    jurisdiction: str,
    evidence_tier: str,
    confidence: float,
    notes: str,
) -> dict[str, Any]:
    return {
        "edge_id": f"INF_{name_hash(from_id + '|' + to_id + '|' + rel)}",
        "source_id": source_id,
        "source_type": source_type,
        "from_entity_id": from_id,
        "from_entity_type": from_type,
        "to_entity_id": to_id,
        "to_entity_type": to_type,
        "relationship_type": rel,
        "relationship_subtype": subtype,
        "filing_year": filing_year,
        "jurisdiction": jurisdiction,
        "evidence_tier": evidence_tier,
        "confidence": confidence,
        "notes": notes,
    }


def build_rows(root: Path | None = None) -> list[dict[str, Any]]:
    """Return the unified influence-edge table; every endpoint resolves to a master id."""
    root = root or REPO_ROOT
    types = _type_index(root)
    by_suffix = {_suffix(i): i for i in types}
    rows: list[dict[str, Any]] = []

    # Lobbying registrations: lobbyist LOBBIES_FOR client.
    for r in _read(root, LOBBYING):
        frm = by_suffix.get(_suffix(r["lobbyist_entity_id"]))
        to = by_suffix.get(_suffix(r["client_entity_id"]))
        if not frm or not to:
            continue
        rows.append(
            _edge(
                "canonical_v1_lobbying_records",
                "pr_cabilderos",
                frm,
                types.get(frm, ""),
                to,
                types.get(to, ""),
                "LOBBIES_FOR",
                (r.get("filing_type") or "").strip(),
                (r.get("period") or "").strip(),
                (r.get("jurisdiction") or "PR").strip(),
                "T3",
                float(r.get("confidence") or 0.0),
                (r.get("notes") or "").strip(),
            )
        )

    # Board / role memberships: person BOARD_MEMBER_OF entity.
    for r in _read(root, ROLES):
        frm = by_suffix.get(_suffix(r["person_id"]))
        to = by_suffix.get(_suffix(r["entity_id"]))
        if not frm or not to:
            continue
        rows.append(
            _edge(
                "canonical_v1_roles",
                "registry",
                frm,
                types.get(frm, ""),
                to,
                types.get(to, ""),
                "BOARD_MEMBER_OF",
                (r.get("role_category") or "").strip(),
                (r.get("start_date") or "").strip(),
                "PR",
                "T2",
                float(r.get("confidence") or 0.0),
                (r.get("role_title") or "").strip(),
            )
        )

    # Parent / operator control (already master ids): child -> parent.
    for r in _read(root, PARENT_MAP):
        rel_in = r["relationship_type"]
        mapped = PARENT_INFLUENCE.get(rel_in)
        if not mapped:
            continue
        rel_out, _direction = mapped
        child, parent = r["child_entity_id"], r["parent_entity_id"]
        rows.append(
            _edge(
                "entity_parent_map",
                "registry",
                child,
                types.get(child, ""),
                parent,
                types.get(parent, ""),
                rel_out,
                rel_in,
                "",
                "PR",
                r["evidence_tier"],
                float(r["confidence"]),
                (r.get("notes") or "").strip(),
            )
        )

    return rows


def check(rows: list[dict[str, Any]], root: Path | None = None) -> list[str]:
    """Return a list of problems (empty == valid)."""
    root = root or REPO_ROOT
    problems: list[str] = []
    if not rows:
        problems.append("no influence edges produced")

    ids = [r["edge_id"] for r in rows]
    # edge_id collides only if two rows share (from, to, relationship_type); that
    # would itself be a duplicate edge, so report it.
    if len(set(ids)) != len(ids):
        problems.append("duplicate edge_id values present (duplicate from/to/relationship)")

    types = _type_index(root)
    schema = _load_schema(root)
    for i, row in enumerate(rows, start=1):
        for msg in validate_row(row, schema):
            problems.append(f"row {i} ({row.get('edge_id')}): {msg}")
        if row["from_entity_id"] not in types:
            problems.append(f"row {i}: from_entity_id {row['from_entity_id']} not in masters")
        if row["to_entity_id"] not in types:
            problems.append(f"row {i}: to_entity_id {row['to_entity_id']} not in masters")
        if row["from_entity_id"] == row["to_entity_id"]:
            problems.append(f"row {i}: self-referential influence edge ({row['from_entity_id']})")
    return problems


def _write(rows: list[dict[str, Any]], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def build(root: Path | None = None) -> dict[str, Any]:
    """Build, validate, and write the influence-edge CSV + manifest."""
    root = root or REPO_ROOT
    rows = build_rows(root)
    problems = check(rows, root)
    if problems:
        raise ValueError("influence_edges check failed: " + "; ".join(problems))
    _write(rows, root / OUT)
    manifest = {
        "producer_script": "scripts/build_influence_edges.py",
        "producer_phase": "TOP_FORM_INFLUENCE_EDGES",
        "schema": SCHEMA,
        "source_inputs": [LOBBYING, ROLES, PARENT_MAP, ENTITY_MASTER, AGENCY_MASTER, PERSON_MASTER],
        "output": OUT,
        "row_count": len(rows),
        "relationship_types": sorted({r["relationship_type"] for r in rows}),
        "source_types": sorted({r["source_type"] for r in rows}),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    manifest_path = root / MANIFEST_OUT
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the top-form Influence Edges.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--check", action="store_true", help="Validate without writing.")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    if args.check:
        rows = build_rows(root)
        problems = check(rows, root)
        print(
            json.dumps({"ok": not problems, "row_count": len(rows), "problems": problems}, indent=2)
        )
        return 0 if not problems else 1
    print(json.dumps(build(root), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
