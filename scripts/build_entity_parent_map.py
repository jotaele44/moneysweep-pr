"""Build the top-form Entity Parent Map (Gate 5, item ``parent_map``).

A schema-locked registry of parent/subsidiary and operator relationships between
master entities: the Commonwealth and its instrumentalities (public corporations
and agencies), and the public-private operators (LUMA, Genera, Metropistas) of
Commonwealth-owned assets. These relationships are curated public facts, so the
authority is a small committed seed (``data/reference/entity_parent_map_seed.csv``)
whose parent/child names are resolved deterministically to master entity_ids and
validated for referential integrity against ``data/reference/entity_master.csv``.

Pure, deterministic, no network. Reuses ``name_hash`` and the stdlib schema
validator (no ``jsonschema`` dep).

CLI::

    python scripts/build_entity_parent_map.py            # write the CSV + manifest
    python scripts/build_entity_parent_map.py --check     # validate without writing
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

from moneysweep.runtime.canonical_ids import name_hash
from moneysweep.validation.canonical_v1_schema import validate_row

REPO_ROOT = Path(__file__).resolve().parents[1]
ENTITY_MASTER = "data/reference/entity_master.csv"
SEED = "data/reference/entity_parent_map_seed.csv"
PARENT_MAP_OUT = "data/reference/entity_parent_map.csv"
MANIFEST_OUT = "data/manifests/entity_parent_map.json"
SCHEMA = "schemas/entity_parent_map.schema.json"
SOURCE_ID = "entity_parent_map_seed"

PARENT_MAP_COLUMNS = [
    "relation_id",
    "parent_entity_id",
    "child_entity_id",
    "relationship_type",
    "source_id",
    "evidence_tier",
    "confidence",
    "notes",
]


def _load_schema(root: Path) -> dict[str, Any]:
    return json.loads((root / SCHEMA).read_text(encoding="utf-8"))


def _name_index(root: Path) -> dict[str, str]:
    """Map entity_master canonical_name -> entity_id."""
    index: dict[str, str] = {}
    with (root / ENTITY_MASTER).open(newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            index[r["canonical_name"].strip()] = r["entity_id"]
    return index


def build_rows(root: Path | None = None) -> list[dict[str, Any]]:
    """Return Entity Parent Map rows from the curated seed, resolved to master ids."""
    root = root or REPO_ROOT
    index = _name_index(root)
    rows: list[dict[str, Any]] = []
    with (root / SEED).open(newline="", encoding="utf-8") as fh:
        for ref in csv.DictReader(fh):
            parent_name = (ref.get("parent_name") or "").strip()
            child_name = (ref.get("child_name") or "").strip()
            rel_type = (ref.get("relationship_type") or "").strip()
            parent_id = index.get(parent_name, "")
            child_id = index.get(child_name, "")
            # Unresolved names are surfaced by check(); keep the row so the error is reported.
            rows.append(
                {
                    "relation_id": f"REL_PARENT_{name_hash(parent_id + '|' + child_id + '|' + rel_type)}",
                    "parent_entity_id": parent_id,
                    "child_entity_id": child_id,
                    "relationship_type": rel_type,
                    "source_id": SOURCE_ID,
                    "evidence_tier": (ref.get("evidence_tier") or "").strip(),
                    "confidence": float(ref.get("confidence") or 0.0),
                    "notes": (ref.get("claim") or "").strip(),
                    "_parent_name": parent_name,
                    "_child_name": child_name,
                }
            )
    return rows


def _public_row(row: dict[str, Any]) -> dict[str, Any]:
    """Drop the private resolution-helper keys (prefixed with '_')."""
    return {k: v for k, v in row.items() if not k.startswith("_")}


def check(rows: list[dict[str, Any]], root: Path | None = None) -> list[str]:
    """Return a list of problems (empty == valid)."""
    root = root or REPO_ROOT
    problems: list[str] = []
    if not rows:
        problems.append("no entity_parent_map rows produced")
    ids = [r["relation_id"] for r in rows]
    if len(set(ids)) != len(ids):
        problems.append("duplicate relation_id values present")
    for i, row in enumerate(rows, start=1):
        if not row["parent_entity_id"]:
            problems.append(
                f"row {i}: parent name {row.get('_parent_name')!r} not found in entity_master"
            )
        if not row["child_entity_id"]:
            problems.append(
                f"row {i}: child name {row.get('_child_name')!r} not found in entity_master"
            )
        if row["parent_entity_id"] and row["parent_entity_id"] == row["child_entity_id"]:
            problems.append(f"row {i}: self-referential relationship ({row['parent_entity_id']})")
    schema = _load_schema(root)
    for i, row in enumerate(rows, start=1):
        for msg in validate_row(_public_row(row), schema):
            problems.append(f"row {i} ({row.get('_child_name')!r}): {msg}")
    return problems


def _write(rows: list[dict[str, Any]], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=PARENT_MAP_COLUMNS)
        writer.writeheader()
        writer.writerows(_public_row(r) for r in rows)


def build(root: Path | None = None) -> dict[str, Any]:
    """Build, validate, and write the Entity Parent Map CSV + manifest."""
    root = root or REPO_ROOT
    rows = build_rows(root)
    problems = check(rows, root)
    if problems:
        raise ValueError("entity_parent_map check failed: " + "; ".join(problems))
    _write(rows, root / PARENT_MAP_OUT)
    manifest = {
        "producer_script": "scripts/build_entity_parent_map.py",
        "producer_phase": "TOP_FORM_PARENT_MAP",
        "schema": SCHEMA,
        "source_inputs": [SEED, ENTITY_MASTER],
        "output": PARENT_MAP_OUT,
        "row_count": len(rows),
        "relationship_types": sorted({r["relationship_type"] for r in rows}),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    manifest_path = root / MANIFEST_OUT
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the top-form Entity Parent Map.")
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
