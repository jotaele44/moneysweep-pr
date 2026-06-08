"""Build the top-form Entity Master reference table (Gate 5, item ``entity_master``).

The Entity Master is the stable, schema-locked registry of every distinct
real-world entity the project tracks. It is intentionally a **higher-level,
export-facing** table, distinct from ``data/canonical_v1/entities.csv`` (the
graph node table): IDs follow the ``ENT_<TYPE>_<hash>`` convention in
``schemas/entity_master.schema.json`` and every row carries an evidence tier
and confidence so downstream gates (influence edges, graph export,
contractor↔donor overlap) can resolve against a single authority.

Source surface: the committed, public, non-PII reference file
``data/reference/pr_public_money_entities.csv``. The transform is pure (no
network, no I/O beyond the committed CSV) and deterministic — the same input
yields byte-identical output across runs.

Reuses the deterministic ID + normalization helpers in
``contract_sweeper.runtime`` and the stdlib schema validator in
``contract_sweeper.validation.canonical_v1_schema`` (no ``jsonschema`` dep).

CLI::

    python scripts/build_entity_master.py            # write the CSV + manifest
    python scripts/build_entity_master.py --check     # validate without writing
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
REFERENCE = "data/reference/pr_public_money_entities.csv"
ENTITY_MASTER_OUT = "data/reference/entity_master.csv"
MANIFEST_OUT = "data/manifests/entity_master.json"
SCHEMA = "schemas/entity_master.schema.json"
SOURCE_ID = "pr_public_money_entities"

# Output column order (matches schema required fields + notes).
ENTITY_MASTER_COLUMNS = [
    "entity_id",
    "entity_type",
    "canonical_name",
    "jurisdiction",
    "source_id",
    "evidence_tier",
    "confidence",
    "notes",
]

# Source entity_type -> schema entity_type enum + ID type-code.
#   schema enum: organization | person | government_agency | municipality | ...
#   ID pattern:  ^ENT_(ORG|PERSON|AGENCY|MUNI|PROJECT|CONTRACT|DEBT|PROPERTY|ASSET)_...
TYPE_MAP: dict[str, tuple[str, str]] = {
    "agency": ("government_agency", "AGENCY"),
    "utility": ("government_agency", "AGENCY"),
    "firm": ("organization", "ORG"),
    "fund": ("organization", "ORG"),
    "nonprofit": ("organization", "ORG"),
    "other": ("organization", "ORG"),
}

EVIDENCE_TIER = "T1"  # committed official/registry reference
CONFIDENCE = 0.95


def _load_schema(root: Path) -> dict[str, Any]:
    return json.loads((root / SCHEMA).read_text(encoding="utf-8"))


def build_rows(root: Path | None = None) -> list[dict[str, Any]]:
    """Return Entity Master rows from the public-money institutions reference."""
    root = root or REPO_ROOT
    rows: list[dict[str, Any]] = []
    with (root / REFERENCE).open(newline="", encoding="utf-8") as fh:
        for ref in csv.DictReader(fh):
            name = (ref.get("name") or "").strip()
            src_type = (ref.get("entity_type") or "").strip().lower()
            if not name or src_type not in TYPE_MAP:
                continue
            schema_type, code = TYPE_MAP[src_type]
            aliases = (ref.get("aliases") or "").strip()
            rows.append(
                {
                    "entity_id": f"ENT_{code}_{name_hash(name)}",
                    "entity_type": schema_type,
                    "canonical_name": name,
                    "jurisdiction": (ref.get("jurisdiction") or "").strip() or "PR",
                    "source_id": SOURCE_ID,
                    "evidence_tier": EVIDENCE_TIER,
                    "confidence": CONFIDENCE,
                    "notes": f"aliases={aliases}" if aliases else "",
                }
            )
    return rows


def check(rows: list[dict[str, Any]], root: Path | None = None) -> list[str]:
    """Return a list of problems (empty == valid)."""
    root = root or REPO_ROOT
    problems: list[str] = []
    if not rows:
        problems.append("no entity_master rows produced")
    ids = [r["entity_id"] for r in rows]
    if len(set(ids)) != len(ids):
        problems.append("duplicate entity_id values present")
    schema = _load_schema(root)
    for i, row in enumerate(rows, start=1):
        for msg in validate_row(row, schema):
            problems.append(f"row {i} ({row.get('canonical_name')!r}): {msg}")
    return problems


def _write(rows: list[dict[str, Any]], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=ENTITY_MASTER_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def build(root: Path | None = None) -> dict[str, Any]:
    """Build, validate, and write the Entity Master CSV + manifest."""
    root = root or REPO_ROOT
    rows = build_rows(root)
    problems = check(rows, root)
    if problems:
        raise ValueError("entity_master check failed: " + "; ".join(problems))
    _write(rows, root / ENTITY_MASTER_OUT)
    manifest = {
        "producer_script": "scripts/build_entity_master.py",
        "producer_phase": "TOP_FORM_ENTITY_MASTER",
        "schema": SCHEMA,
        "source_inputs": [REFERENCE],
        "output": ENTITY_MASTER_OUT,
        "row_count": len(rows),
        "entity_types": sorted({r["entity_type"] for r in rows}),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    manifest_path = root / MANIFEST_OUT
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build the top-form Entity Master reference table."
    )
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
