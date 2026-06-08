"""Build the top-form Agency Master reference table (Gate 5, item ``agency_master``).

The Agency Master is the stable, schema-locked registry of every government body
and authority the project tracks: Commonwealth agencies and public corporations
(PREPA, PRASA, FOMB, COFINA, HTA, …) plus the 78 Puerto Rico municipios. It is a
focused, agency-only sibling of the Entity Master — IDs follow the
``ENT_AGENCY_<hash>`` / ``ENT_MUNI_<code>`` convention in
``schemas/agency_master.schema.json`` and every row carries an evidence tier and
confidence so downstream gates (agency normalization, influence edges, graph
export) can resolve against a single agency authority. Unlike the Entity Master,
aliases are broken out as a first-class column ("normalize agencies and
authorities").

Source surface (committed, public, non-PII, deterministic — no network):
  * ``data/reference/pr_public_money_entities.csv`` rows where ``entity_type`` is
    ``agency`` (→ government_agency) or ``utility`` (→ public_corporation).
  * ``data/reference/pr_municipalities.csv`` — the 78 municipios (→ municipality).

Reuses the deterministic ID helper in ``contract_sweeper.runtime`` and the stdlib
schema validator in ``contract_sweeper.validation.canonical_v1_schema`` (no
``jsonschema`` dep).

CLI::

    python scripts/build_agency_master.py            # write the CSV + manifest
    python scripts/build_agency_master.py --check     # validate without writing
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
PUBLIC_MONEY = "data/reference/pr_public_money_entities.csv"
MUNICIPALITIES = "data/reference/pr_municipalities.csv"
AGENCY_MASTER_OUT = "data/reference/agency_master.csv"
MANIFEST_OUT = "data/manifests/agency_master.json"
SCHEMA = "schemas/agency_master.schema.json"

# Output column order (schema required fields + aliases/notes).
AGENCY_MASTER_COLUMNS = [
    "agency_id",
    "agency_type",
    "canonical_name",
    "jurisdiction",
    "aliases",
    "source_id",
    "evidence_tier",
    "confidence",
    "notes",
]

# Public-money source entity_type -> schema agency_type.
PUBLIC_MONEY_TYPE_MAP: dict[str, str] = {
    "agency": "government_agency",
    "utility": "public_corporation",
}

EVIDENCE_TIER = "T1"  # committed official/registry reference
CONFIDENCE = 0.95


def _load_schema(root: Path) -> dict[str, Any]:
    return json.loads((root / SCHEMA).read_text(encoding="utf-8"))


def build_rows(root: Path | None = None) -> list[dict[str, Any]]:
    """Return Agency Master rows from the public-money + municipality references."""
    root = root or REPO_ROOT
    rows: list[dict[str, Any]] = []

    # Government agencies and public corporations.
    with (root / PUBLIC_MONEY).open(newline="", encoding="utf-8") as fh:
        for ref in csv.DictReader(fh):
            name = (ref.get("name") or "").strip()
            src_type = (ref.get("entity_type") or "").strip().lower()
            agency_type = PUBLIC_MONEY_TYPE_MAP.get(src_type)
            if not name or agency_type is None:
                continue
            rows.append(
                {
                    "agency_id": f"ENT_AGENCY_{name_hash(name)}",
                    "agency_type": agency_type,
                    "canonical_name": name,
                    "jurisdiction": (ref.get("jurisdiction") or "").strip() or "PR",
                    "aliases": (ref.get("aliases") or "").strip(),
                    "source_id": "pr_public_money_entities",
                    "evidence_tier": EVIDENCE_TIER,
                    "confidence": CONFIDENCE,
                    "notes": (ref.get("description") or "").strip(),
                }
            )

    # The 78 municipios as municipal authorities.
    with (root / MUNICIPALITIES).open(newline="", encoding="utf-8") as fh:
        for ref in csv.DictReader(fh):
            name = (ref.get("canonical_name") or "").strip()
            code = (ref.get("municipality_code") or "").strip()
            if not name or not code:
                continue
            region = (ref.get("region") or "").strip()
            rows.append(
                {
                    "agency_id": f"ENT_MUNI_{code}",
                    "agency_type": "municipality",
                    "canonical_name": name,
                    "jurisdiction": "PR",
                    "aliases": (ref.get("aliases") or "").strip(),
                    "source_id": "pr_municipalities",
                    "evidence_tier": EVIDENCE_TIER,
                    "confidence": CONFIDENCE,
                    "notes": f"region={region}" if region else "",
                }
            )

    return rows


def check(rows: list[dict[str, Any]], root: Path | None = None) -> list[str]:
    """Return a list of problems (empty == valid)."""
    root = root or REPO_ROOT
    problems: list[str] = []
    if not rows:
        problems.append("no agency_master rows produced")
    ids = [r["agency_id"] for r in rows]
    if len(set(ids)) != len(ids):
        problems.append("duplicate agency_id values present")
    schema = _load_schema(root)
    for i, row in enumerate(rows, start=1):
        for msg in validate_row(row, schema):
            problems.append(f"row {i} ({row.get('canonical_name')!r}): {msg}")
    return problems


def _write(rows: list[dict[str, Any]], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=AGENCY_MASTER_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def build(root: Path | None = None) -> dict[str, Any]:
    """Build, validate, and write the Agency Master CSV + manifest."""
    root = root or REPO_ROOT
    rows = build_rows(root)
    problems = check(rows, root)
    if problems:
        raise ValueError("agency_master check failed: " + "; ".join(problems))
    _write(rows, root / AGENCY_MASTER_OUT)
    manifest = {
        "producer_script": "scripts/build_agency_master.py",
        "producer_phase": "TOP_FORM_AGENCY_MASTER",
        "schema": SCHEMA,
        "source_inputs": [PUBLIC_MONEY, MUNICIPALITIES],
        "output": AGENCY_MASTER_OUT,
        "row_count": len(rows),
        "agency_types": sorted({r["agency_type"] for r in rows}),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    manifest_path = root / MANIFEST_OUT
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build the top-form Agency Master reference table."
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
