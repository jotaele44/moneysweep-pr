"""Build the top-form Entity Aliases table (Gate 5, item ``entity_aliases``).

A long-form alias registry: one row per ``(entity_id, alias)`` pair, exploded
deterministically from the committed master tables so downstream gates and the
name-resolution layer can join an alternate name straight to a master entity_id.
Aliases already live (pipe-delimited) inside the masters:

  * ``data/reference/entity_master.csv`` — in the ``notes`` column as ``aliases=...``
    (covers the 26 organization/agency entities).
  * ``data/reference/agency_master.csv`` — first-class ``aliases`` column; only the
    ``ENT_MUNI_`` rows (78 municipios) are taken here, since the 17 agencies share
    ids with entity_master and are already covered above (no duplicates).

Person entities carry no aliases in the source, so they are not represented.

Pure, deterministic, no network. Reuses ``name_hash`` /
``normalize_name`` and the stdlib schema validator (no ``jsonschema`` dep).

CLI::

    python scripts/build_entity_aliases.py            # write the CSV + manifest
    python scripts/build_entity_aliases.py --check     # validate without writing
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
from contract_sweeper.runtime.name_normalization import normalize_name
from contract_sweeper.validation.canonical_v1_schema import validate_row

REPO_ROOT = Path(__file__).resolve().parents[1]
ENTITY_MASTER = "data/reference/entity_master.csv"
AGENCY_MASTER = "data/reference/agency_master.csv"
ENTITY_ALIASES_OUT = "data/reference/entity_aliases.csv"
MANIFEST_OUT = "data/manifests/entity_aliases.json"
SCHEMA = "schemas/entity_aliases.schema.json"
ALIASES_PREFIX = "aliases="

ENTITY_ALIASES_COLUMNS = [
    "alias_id",
    "entity_id",
    "alias",
    "normalized_alias",
    "source_id",
    "evidence_tier",
    "confidence",
    "notes",
]

EVIDENCE_TIER = "T1"
CONFIDENCE = 0.95


def _load_schema(root: Path) -> dict[str, Any]:
    return json.loads((root / SCHEMA).read_text(encoding="utf-8"))


def _split_aliases(raw: str) -> list[str]:
    """Split a pipe-delimited alias string into stripped, non-empty parts."""
    return [p.strip() for p in (raw or "").split("|") if p.strip()]


def _master_entity_ids(root: Path) -> set[str]:
    """All committed master ids (entity_master + agency_master), for integrity checks."""
    ids: set[str] = set()
    with (root / ENTITY_MASTER).open(newline="", encoding="utf-8") as fh:
        ids.update(r["entity_id"] for r in csv.DictReader(fh))
    with (root / AGENCY_MASTER).open(newline="", encoding="utf-8") as fh:
        ids.update(r["agency_id"] for r in csv.DictReader(fh))
    return ids


def build_rows(root: Path | None = None) -> list[dict[str, Any]]:
    """Return Entity Alias rows exploded from the master tables."""
    root = root or REPO_ROOT
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    def _emit(entity_id: str, alias: str, source_id: str) -> None:
        normalized = normalize_name(alias)
        key = (entity_id, normalized)
        if not alias or key in seen:
            return
        seen.add(key)
        rows.append(
            {
                "alias_id": f"ENT_ALIAS_{name_hash(entity_id + '|' + normalized)}",
                "entity_id": entity_id,
                "alias": alias,
                "normalized_alias": normalized,
                "source_id": source_id,
                "evidence_tier": EVIDENCE_TIER,
                "confidence": CONFIDENCE,
                "notes": "",
            }
        )

    # Organizations + agencies: aliases live in the notes column as ``aliases=...``.
    with (root / ENTITY_MASTER).open(newline="", encoding="utf-8") as fh:
        for ref in csv.DictReader(fh):
            notes = (ref.get("notes") or "").strip()
            if not notes.startswith(ALIASES_PREFIX):
                continue
            for alias in _split_aliases(notes[len(ALIASES_PREFIX) :]):
                _emit(ref["entity_id"], alias, (ref.get("source_id") or "").strip())

    # Municipios only (ENT_MUNI_): first-class aliases column on agency_master.
    with (root / AGENCY_MASTER).open(newline="", encoding="utf-8") as fh:
        for ref in csv.DictReader(fh):
            agency_id = ref["agency_id"]
            if not agency_id.startswith("ENT_MUNI_"):
                continue
            for alias in _split_aliases(ref.get("aliases") or ""):
                _emit(agency_id, alias, (ref.get("source_id") or "").strip())

    return rows


def check(rows: list[dict[str, Any]], root: Path | None = None) -> list[str]:
    """Return a list of problems (empty == valid)."""
    root = root or REPO_ROOT
    problems: list[str] = []
    if not rows:
        problems.append("no entity_aliases rows produced")
    ids = [r["alias_id"] for r in rows]
    if len(set(ids)) != len(ids):
        problems.append("duplicate alias_id values present")
    known = _master_entity_ids(root)
    for i, row in enumerate(rows, start=1):
        if row["entity_id"] not in known:
            problems.append(f"row {i}: entity_id {row['entity_id']} not found in any master table")
    schema = _load_schema(root)
    for i, row in enumerate(rows, start=1):
        for msg in validate_row(row, schema):
            problems.append(f"row {i} ({row.get('alias')!r}): {msg}")
    return problems


def _write(rows: list[dict[str, Any]], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=ENTITY_ALIASES_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def build(root: Path | None = None) -> dict[str, Any]:
    """Build, validate, and write the Entity Aliases CSV + manifest."""
    root = root or REPO_ROOT
    rows = build_rows(root)
    problems = check(rows, root)
    if problems:
        raise ValueError("entity_aliases check failed: " + "; ".join(problems))
    _write(rows, root / ENTITY_ALIASES_OUT)
    manifest = {
        "producer_script": "scripts/build_entity_aliases.py",
        "producer_phase": "TOP_FORM_ENTITY_ALIASES",
        "schema": SCHEMA,
        "source_inputs": [ENTITY_MASTER, AGENCY_MASTER],
        "output": ENTITY_ALIASES_OUT,
        "row_count": len(rows),
        "distinct_entities": len({r["entity_id"] for r in rows}),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    manifest_path = root / MANIFEST_OUT
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the top-form Entity Aliases table.")
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
