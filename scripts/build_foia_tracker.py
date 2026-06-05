"""Build the FOIA / public-records priority queue (Gate ``foia``, item ``foia_tracker``).

A schema-locked request tracker whose targets are derived from the project's own
unmet-source gaps: each row is a public-records request for a source that the
pipeline needs but cannot materialize in-sandbox (credentialed exports,
key-gated APIs, manual dropzones). The authority is a curated seed
(``data/reference/foia_priority_queue_seed.csv``) keyed by ``source_id``; the
producer validates every target against ``reports/source_registry_status.csv`` —
the target must exist and must NOT already be fully materialized, so the queue
only ever tracks real gaps.

Pure, deterministic, no network. Reuses ``name_hash`` and the stdlib schema
validator (no ``jsonschema`` dep).

CLI::

    python scripts/build_foia_tracker.py            # write the CSV + manifest
    python scripts/build_foia_tracker.py --check     # validate without writing
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

SEED = "data/reference/foia_priority_queue_seed.csv"
SOURCE_STATUS = "reports/source_registry_status.csv"
OUT = "reports/foia_priority_queue.csv"
MANIFEST_OUT = "data/manifests/foia_priority_queue.json"
SCHEMA = "schemas/foia_request.schema.json"
SOURCE_ID = "foia_priority_queue_seed"
EVIDENCE_TIER = "T2"
CONFIDENCE = 0.8

COLUMNS = [
    "request_id", "target_source_id", "target_agency", "jurisdiction",
    "record_type", "statute", "request_status", "priority", "rationale",
    "evidence_tier", "confidence", "notes",
]


def _load_schema(root: Path) -> dict[str, Any]:
    return json.loads((root / SCHEMA).read_text(encoding="utf-8"))


def _read(root: Path, rel: str) -> list[dict[str, str]]:
    with (root / rel).open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _source_status_index(root: Path) -> dict[str, str]:
    """Map source_id -> pipeline_status from the source registry status report."""
    return {r["source_id"]: (r.get("pipeline_status") or "").strip()
            for r in _read(root, SOURCE_STATUS)}


def build_rows(root: Path | None = None) -> list[dict[str, Any]]:
    """Return FOIA request rows from the curated seed."""
    root = root or REPO_ROOT
    status = _source_status_index(root)
    rows: list[dict[str, Any]] = []
    for ref in _read(root, SEED):
        source_id = (ref.get("target_source_id") or "").strip()
        record_type = (ref.get("record_type") or "").strip()
        rows.append({
            "request_id": f"FOIA_{name_hash(source_id + '|' + record_type)}",
            "target_source_id": source_id,
            "target_agency": (ref.get("target_agency") or "").strip(),
            "jurisdiction": (ref.get("jurisdiction") or "").strip(),
            "record_type": record_type,
            "statute": (ref.get("statute") or "").strip(),
            "request_status": (ref.get("request_status") or "planned").strip(),
            "priority": (ref.get("priority") or "").strip(),
            "rationale": (ref.get("rationale") or "").strip(),
            "evidence_tier": EVIDENCE_TIER,
            "confidence": CONFIDENCE,
            "notes": "",
            "_source_status": status.get(source_id),
        })
    return rows


def _public_row(row: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in row.items() if not k.startswith("_")}


def check(rows: list[dict[str, Any]], root: Path | None = None) -> list[str]:
    """Return a list of problems (empty == valid)."""
    root = root or REPO_ROOT
    problems: list[str] = []
    if not rows:
        problems.append("no FOIA requests produced")
    ids = [r["request_id"] for r in rows]
    if len(set(ids)) != len(ids):
        problems.append("duplicate request_id values present")
    targets = [r["target_source_id"] for r in rows]
    if len(set(targets)) != len(targets):
        problems.append("duplicate target_source_id values present")
    schema = _load_schema(root)
    for i, row in enumerate(rows, start=1):
        # Referential integrity: only track real, unmet source gaps.
        st = row.get("_source_status")
        if st is None:
            problems.append(f"row {i}: target {row['target_source_id']!r} not found in source registry status")
        elif st == "fully_materialized":
            problems.append(f"row {i}: target {row['target_source_id']!r} is already fully_materialized — not a gap")
        for msg in validate_row(_public_row(row), schema):
            problems.append(f"row {i} ({row.get('target_source_id')!r}): {msg}")
    return problems


def _write(rows: list[dict[str, Any]], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(_public_row(r) for r in rows)


def build(root: Path | None = None) -> dict[str, Any]:
    """Build, validate, and write the FOIA priority queue CSV + manifest."""
    root = root or REPO_ROOT
    rows = build_rows(root)
    problems = check(rows, root)
    if problems:
        raise ValueError("foia_tracker check failed: " + "; ".join(problems))
    _write(rows, root / OUT)
    manifest = {
        "producer_script": "scripts/build_foia_tracker.py",
        "producer_phase": "TOP_FORM_FOIA_TRACKER",
        "schema": SCHEMA,
        "source_inputs": [SEED, SOURCE_STATUS],
        "output": OUT,
        "row_count": len(rows),
        "jurisdictions": sorted({r["jurisdiction"] for r in rows}),
        "priorities": sorted({r["priority"] for r in rows}),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    manifest_path = root / MANIFEST_OUT
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the FOIA / public-records priority queue.")
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
