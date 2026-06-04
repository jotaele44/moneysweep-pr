"""Build the top-form Debt Instruments registry (Gate ``debt_fiscal``,
item ``debt_instrument_schema``).

Locks ``schemas/debt_instrument.schema.json`` into a deterministic producer: a
top-form view of the committed canonical bond table with each issuer resolved
from its canonical_v1 id (``entity_<hash>``) to a master entity_id
(``ENT_*_<hash>``) and named from ``entity_master.csv``.

Input:  ``data/canonical_v1/debt_instruments.csv`` (20 bonds) + ``entity_master.csv``
Output: ``data/reference/debt_instruments.csv`` + ``data/manifests/debt_instruments.json``

Reuses the stdlib schema validator (no ``jsonschema`` dep).

CLI::

    python scripts/build_debt_instruments.py            # write the CSV + manifest
    python scripts/build_debt_instruments.py --check     # validate without writing
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

CANONICAL_DEBT = "data/canonical_v1/debt_instruments.csv"
ENTITY_MASTER = "data/reference/entity_master.csv"
OUT = "data/reference/debt_instruments.csv"
MANIFEST_OUT = "data/manifests/debt_instruments.json"
SCHEMA = "schemas/debt_instrument.schema.json"
SOURCE_ID = "canonical_v1_debt_instruments"
EVIDENCE_TIER = "T2"  # EMMA known-bond reference seed; below official T1.

COLUMNS = [
    "debt_id", "issuer_entity_id", "issuer_name", "debt_class", "series",
    "issue_year", "par_amount", "currency", "maturity_date",
    "evidence_tier", "confidence", "notes",
]


def _load_schema(root: Path) -> dict[str, Any]:
    return json.loads((root / SCHEMA).read_text(encoding="utf-8"))


def _read(root: Path, rel: str) -> list[dict[str, str]]:
    with (root / rel).open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _issuer_index(root: Path) -> dict[str, tuple[str, str]]:
    """Map the shared hash suffix -> (master entity_id, canonical_name)."""
    index: dict[str, tuple[str, str]] = {}
    for r in _read(root, ENTITY_MASTER):
        index[r["entity_id"].rsplit("_", 1)[-1]] = (r["entity_id"], r["canonical_name"])
    return index


def build_rows(root: Path | None = None) -> list[dict[str, Any]]:
    """Return the top-form debt-instrument rows, issuer resolved to master ids."""
    root = root or REPO_ROOT
    index = _issuer_index(root)
    rows: list[dict[str, Any]] = []
    for r in _read(root, CANONICAL_DEBT):
        suffix = r["issuer_entity_id"].rsplit("_", 1)[-1]
        issuer_id, issuer_name = index.get(suffix, ("", ""))
        par = r.get("par_amount") or ""
        year = r.get("issue_year") or ""
        rows.append({
            "debt_id": r["debt_id"],
            "issuer_entity_id": issuer_id,
            "issuer_name": issuer_name,
            "debt_class": r["debt_class"],
            "series": (r.get("series") or "").strip(),
            "issue_year": int(year) if year else "",
            "par_amount": float(par) if par else "",
            "currency": r.get("currency") or "USD",
            "maturity_date": (r.get("maturity_date") or "").strip(),
            "evidence_tier": EVIDENCE_TIER,
            "confidence": float(r.get("confidence") or 0.0),
            "notes": (r.get("notes") or "").strip(),
            "_source_issuer": r["issuer_entity_id"],
        })
    return rows


def _public_row(row: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in row.items() if not k.startswith("_")}


def check(rows: list[dict[str, Any]], root: Path | None = None) -> list[str]:
    """Return a list of problems (empty == valid)."""
    root = root or REPO_ROOT
    problems: list[str] = []
    if not rows:
        problems.append("no debt instruments produced")
    ids = [r["debt_id"] for r in rows]
    if len(set(ids)) != len(ids):
        problems.append("duplicate debt_id values present")
    schema = _load_schema(root)
    for i, row in enumerate(rows, start=1):
        if not row["issuer_entity_id"]:
            problems.append(f"row {i}: issuer {row.get('_source_issuer')!r} not resolved in entity_master")
        for msg in validate_row(_public_row(row), schema):
            problems.append(f"row {i} ({row.get('debt_id')}): {msg}")
    return problems


def _write(rows: list[dict[str, Any]], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(_public_row(r) for r in rows)


def build(root: Path | None = None) -> dict[str, Any]:
    """Build, validate, and write the debt-instruments CSV + manifest."""
    root = root or REPO_ROOT
    rows = build_rows(root)
    problems = check(rows, root)
    if problems:
        raise ValueError("debt_instruments check failed: " + "; ".join(problems))
    _write(rows, root / OUT)
    total_par = sum(float(r["par_amount"]) for r in rows if r["par_amount"] != "")
    manifest = {
        "producer_script": "scripts/build_debt_instruments.py",
        "producer_phase": "TOP_FORM_DEBT_INSTRUMENTS",
        "schema": SCHEMA,
        "source_inputs": [CANONICAL_DEBT, ENTITY_MASTER],
        "output": OUT,
        "row_count": len(rows),
        "issuer_count": len({r["issuer_entity_id"] for r in rows}),
        "total_par": total_par,
        "debt_classes": sorted({r["debt_class"] for r in rows}),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    manifest_path = root / MANIFEST_OUT
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the top-form Debt Instruments registry.")
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
