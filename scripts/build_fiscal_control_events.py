"""Build the top-form Fiscal Control Events timeline (Gate ``debt_fiscal``,
item ``fiscal_control_events``).

A schema-locked timeline of Puerto Rico's fiscal-control and debt-restructuring
milestones (PROMESA, the Oversight Board, Title III filings, plans of
adjustment, and the energy P3 transitions). These are well-documented public
facts, so the authority is a small committed seed
(``data/reference/fiscal_control_events_seed.csv``) whose ``related_entity``
names are resolved deterministically to master entity_ids.

Input:  the seed + ``data/reference/entity_master.csv``
Output: ``data/reference/fiscal_control_events.csv`` + ``data/manifests/fiscal_control_events.json``

Reuses ``name_hash`` and the stdlib schema validator (no ``jsonschema`` dep).

CLI::

    python scripts/build_fiscal_control_events.py            # write the CSV + manifest
    python scripts/build_fiscal_control_events.py --check     # validate without writing
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

SEED = "data/reference/fiscal_control_events_seed.csv"
ENTITY_MASTER = "data/reference/entity_master.csv"
OUT = "data/reference/fiscal_control_events.csv"
MANIFEST_OUT = "data/manifests/fiscal_control_events.json"
SCHEMA = "schemas/fiscal_control_event.schema.json"
SOURCE_ID = "fiscal_control_events_seed"

# Tier -> confidence: T1 = documented public record, T2 = well-attested.
TIER_CONFIDENCE = {"T1": 0.95, "T2": 0.85, "T3": 0.7, "T4": 0.5}

COLUMNS = [
    "event_id", "event_date", "event_type", "title",
    "related_entity_id", "related_entity_name", "claim",
    "source_id", "evidence_tier", "confidence", "notes",
]


def _load_schema(root: Path) -> dict[str, Any]:
    return json.loads((root / SCHEMA).read_text(encoding="utf-8"))


def _read(root: Path, rel: str) -> list[dict[str, str]]:
    with (root / rel).open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _name_index(root: Path) -> dict[str, str]:
    return {r["canonical_name"].strip(): r["entity_id"] for r in _read(root, ENTITY_MASTER)}


def build_rows(root: Path | None = None) -> list[dict[str, Any]]:
    """Return the fiscal-control-event rows from the curated seed."""
    root = root or REPO_ROOT
    index = _name_index(root)
    rows: list[dict[str, Any]] = []
    for ref in _read(root, SEED):
        date = (ref.get("event_date") or "").strip()
        title = (ref.get("title") or "").strip()
        related_name = (ref.get("related_entity") or "").strip()
        tier = (ref.get("evidence_tier") or "").strip()
        rows.append({
            "event_id": f"FCE_{name_hash(date + '|' + title)}",
            "event_date": date,
            "event_type": (ref.get("event_type") or "").strip(),
            "title": title,
            "related_entity_id": index.get(related_name, ""),
            "related_entity_name": related_name,
            "claim": (ref.get("claim") or "").strip(),
            "source_id": SOURCE_ID,
            "evidence_tier": tier,
            "confidence": TIER_CONFIDENCE.get(tier, 0.0),
            "notes": "",
            "_related_name": related_name,
        })
    return rows


def _public_row(row: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in row.items() if not k.startswith("_")}


def check(rows: list[dict[str, Any]], root: Path | None = None) -> list[str]:
    """Return a list of problems (empty == valid)."""
    root = root or REPO_ROOT
    problems: list[str] = []
    if not rows:
        problems.append("no fiscal control events produced")
    ids = [r["event_id"] for r in rows]
    if len(set(ids)) != len(ids):
        problems.append("duplicate event_id values present")
    schema = _load_schema(root)
    for i, row in enumerate(rows, start=1):
        # A named related_entity must resolve; an empty one (e.g. federal law) is allowed.
        if row["_related_name"] and not row["related_entity_id"]:
            problems.append(f"row {i}: related_entity {row['_related_name']!r} not found in entity_master")
        for msg in validate_row(_public_row(row), schema):
            problems.append(f"row {i} ({row.get('title')!r}): {msg}")
    return problems


def _write(rows: list[dict[str, Any]], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(_public_row(r) for r in rows)


def build(root: Path | None = None) -> dict[str, Any]:
    """Build, validate, and write the fiscal-control-events CSV + manifest."""
    root = root or REPO_ROOT
    rows = build_rows(root)
    problems = check(rows, root)
    if problems:
        raise ValueError("fiscal_control_events check failed: " + "; ".join(problems))
    _write(rows, root / OUT)
    manifest = {
        "producer_script": "scripts/build_fiscal_control_events.py",
        "producer_phase": "TOP_FORM_FISCAL_CONTROL_EVENTS",
        "schema": SCHEMA,
        "source_inputs": [SEED, ENTITY_MASTER],
        "output": OUT,
        "row_count": len(rows),
        "event_types": sorted({r["event_type"] for r in rows}),
        "date_range": [min(r["event_date"] for r in rows), max(r["event_date"] for r in rows)],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    manifest_path = root / MANIFEST_OUT
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the top-form Fiscal Control Events timeline.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--check", action="store_true", help="Validate without writing.")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    if args.check:
        rows = build_rows(root)
        problems = check(rows, root)
        print(json.dumps({"ok": not problems, "row_count": len(rows), "problems": problems}, indent=2))
        return 0 if not problems else 1
    print(json.dumps(build(root), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
