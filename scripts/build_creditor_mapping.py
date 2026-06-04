"""Build the top-form Creditor Mapping registry (Gate ``debt_fiscal``,
item ``creditor_mapping``).

Derives an issuer-level creditor registry from the top-form debt-instruments
table: one row per issuing entity with its debt classes, instrument count, and
total par outstanding. Pure aggregation of committed data — no curation, no
network.

Input:  ``data/reference/debt_instruments.csv`` (built by build_debt_instruments.py)
Output: ``data/reference/creditor_mapping.csv`` + ``data/manifests/creditor_mapping.json``

Reuses the stdlib schema validator (no ``jsonschema`` dep).

CLI::

    python scripts/build_creditor_mapping.py            # write the CSV + manifest
    python scripts/build_creditor_mapping.py --check     # validate without writing
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

from contract_sweeper.validation.canonical_v1_schema import validate_row

REPO_ROOT = Path(__file__).resolve().parents[1]

DEBT_INSTRUMENTS = "data/reference/debt_instruments.csv"
OUT = "data/reference/creditor_mapping.csv"
MANIFEST_OUT = "data/manifests/creditor_mapping.json"
SCHEMA = "schemas/creditor_mapping.schema.json"
EVIDENCE_TIER = "T2"

COLUMNS = [
    "issuer_entity_id", "canonical_name", "debt_classes", "instrument_count",
    "total_par", "currency", "evidence_tier", "confidence", "notes",
]


def _load_schema(root: Path) -> dict[str, Any]:
    return json.loads((root / SCHEMA).read_text(encoding="utf-8"))


def _read(root: Path, rel: str) -> list[dict[str, str]]:
    with (root / rel).open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def build_rows(root: Path | None = None) -> list[dict[str, Any]]:
    """Return one creditor row per issuer, aggregated from debt_instruments.csv."""
    root = root or REPO_ROOT
    groups: dict[str, dict[str, Any]] = {}
    for r in _read(root, DEBT_INSTRUMENTS):
        issuer = r["issuer_entity_id"]
        g = groups.setdefault(issuer, {
            "issuer_entity_id": issuer,
            "canonical_name": r["issuer_name"],
            "_classes": set(),
            "instrument_count": 0,
            "total_par": 0.0,
            "currency": r.get("currency") or "USD",
            "_confidences": [],
        })
        g["_classes"].add(r["debt_class"])
        g["instrument_count"] += 1
        g["total_par"] += float(r["par_amount"]) if r.get("par_amount") else 0.0
        g["_confidences"].append(float(r["confidence"]) if r.get("confidence") else 0.0)

    rows: list[dict[str, Any]] = []
    for issuer in sorted(groups, key=lambda k: (-groups[k]["total_par"], k)):
        g = groups[issuer]
        rows.append({
            "issuer_entity_id": g["issuer_entity_id"],
            "canonical_name": g["canonical_name"],
            "debt_classes": "|".join(sorted(g["_classes"])),
            "instrument_count": g["instrument_count"],
            "total_par": g["total_par"],
            "currency": g["currency"],
            "evidence_tier": EVIDENCE_TIER,
            "confidence": round(min(g["_confidences"]), 4) if g["_confidences"] else 0.0,
            "notes": "",
        })
    return rows


def check(rows: list[dict[str, Any]], root: Path | None = None) -> list[str]:
    """Return a list of problems (empty == valid)."""
    root = root or REPO_ROOT
    problems: list[str] = []
    if not rows:
        problems.append("no creditor rows produced")
    ids = [r["issuer_entity_id"] for r in rows]
    if len(set(ids)) != len(ids):
        problems.append("duplicate issuer_entity_id values present")
    schema = _load_schema(root)
    for i, row in enumerate(rows, start=1):
        for msg in validate_row(row, schema):
            problems.append(f"row {i} ({row.get('issuer_entity_id')}): {msg}")
    return problems


def _write(rows: list[dict[str, Any]], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def build(root: Path | None = None) -> dict[str, Any]:
    """Build, validate, and write the creditor-mapping CSV + manifest."""
    root = root or REPO_ROOT
    rows = build_rows(root)
    problems = check(rows, root)
    if problems:
        raise ValueError("creditor_mapping check failed: " + "; ".join(problems))
    _write(rows, root / OUT)
    manifest = {
        "producer_script": "scripts/build_creditor_mapping.py",
        "producer_phase": "TOP_FORM_CREDITOR_MAPPING",
        "schema": SCHEMA,
        "source_inputs": [DEBT_INSTRUMENTS],
        "output": OUT,
        "row_count": len(rows),
        "total_par": sum(r["total_par"] for r in rows),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    manifest_path = root / MANIFEST_OUT
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the top-form Creditor Mapping registry.")
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
