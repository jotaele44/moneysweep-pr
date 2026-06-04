"""Build the Entity Resolution Review Queue (Gate 5, item ``review_queue``).

Stabilizes the review-queue format around the existing canonical schema
``schemas/canonical_v1/review_queue.schema.json`` and emits a deterministic,
human-facing report at ``reports/entity_resolution_review_queue.csv``. It is an
*active* queue: it surfaces master rows that warrant human review before
promotion — currently the lower-confidence Person Master entries (confidence
below ``CONFIDENCE_THRESHOLD``) — as schema-conformant review items.

Pure, deterministic, no network. Reuses ``name_hash`` and the stdlib schema
validator (no ``jsonschema`` dep).

CLI::

    python scripts/build_entity_resolution_review_queue.py            # write CSV + manifest
    python scripts/build_entity_resolution_review_queue.py --check     # validate without writing
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
PERSON_MASTER = "data/reference/person_master.csv"
REVIEW_QUEUE_OUT = "reports/entity_resolution_review_queue.csv"
MANIFEST_OUT = "data/manifests/entity_resolution_review_queue.json"
SCHEMA = "schemas/canonical_v1/review_queue.schema.json"

CONFIDENCE_THRESHOLD = 0.90

# Schema column order (canonical_v1 review_queue item).
REVIEW_QUEUE_COLUMNS = [
    "review_id", "object_type", "object_id", "issue_type", "raw_value",
    "candidate_match", "source_name", "source_ref", "severity",
    "recommended_action", "status",
]


def _load_schema(root: Path) -> dict[str, Any]:
    return json.loads((root / SCHEMA).read_text(encoding="utf-8"))


def build_rows(root: Path | None = None) -> list[dict[str, Any]]:
    """Return review-queue items for master rows needing human review."""
    root = root or REPO_ROOT
    rows: list[dict[str, Any]] = []
    with (root / PERSON_MASTER).open(newline="", encoding="utf-8") as fh:
        for ref in csv.DictReader(fh):
            try:
                confidence = float(ref.get("confidence") or 0.0)
            except ValueError:
                confidence = 0.0
            if confidence >= CONFIDENCE_THRESHOLD:
                continue
            object_id = (ref.get("person_id") or "").strip()
            issue_type = "low_confidence"
            rows.append({
                "review_id": f"review_{name_hash(object_id + '|' + issue_type)}",
                "object_type": "person",
                "object_id": object_id,
                "issue_type": issue_type,
                "raw_value": (ref.get("canonical_name") or "").strip(),
                "candidate_match": "",
                "source_name": (ref.get("source_id") or "").strip(),
                "source_ref": (ref.get("source_person_id") or "").strip(),
                "severity": "medium",
                "recommended_action": "verify against a primary source before promotion",
                "status": "open",
            })
    return rows


def check(rows: list[dict[str, Any]], root: Path | None = None) -> list[str]:
    """Return a list of problems (empty == valid)."""
    root = root or REPO_ROOT
    problems: list[str] = []
    if not rows:
        problems.append("no review_queue rows produced")
    ids = [r["review_id"] for r in rows]
    if len(set(ids)) != len(ids):
        problems.append("duplicate review_id values present")
    # Referential integrity: every queued object_id must exist in the person master.
    known = set()
    with (root / PERSON_MASTER).open(newline="", encoding="utf-8") as fh:
        known.update(r["person_id"] for r in csv.DictReader(fh))
    for i, row in enumerate(rows, start=1):
        if row["object_id"] not in known:
            problems.append(f"row {i}: object_id {row['object_id']} not found in person_master")
    schema = _load_schema(root)
    for i, row in enumerate(rows, start=1):
        for msg in validate_row(row, schema):
            problems.append(f"row {i} ({row.get('raw_value')!r}): {msg}")
    return problems


def _write(rows: list[dict[str, Any]], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=REVIEW_QUEUE_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def build(root: Path | None = None) -> dict[str, Any]:
    """Build, validate, and write the review-queue report + manifest."""
    root = root or REPO_ROOT
    rows = build_rows(root)
    problems = check(rows, root)
    if problems:
        raise ValueError("review_queue check failed: " + "; ".join(problems))
    _write(rows, root / REVIEW_QUEUE_OUT)
    manifest = {
        "producer_script": "scripts/build_entity_resolution_review_queue.py",
        "producer_phase": "TOP_FORM_REVIEW_QUEUE",
        "schema": SCHEMA,
        "source_inputs": [PERSON_MASTER],
        "output": REVIEW_QUEUE_OUT,
        "row_count": len(rows),
        "confidence_threshold": CONFIDENCE_THRESHOLD,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    manifest_path = root / MANIFEST_OUT
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the Entity Resolution Review Queue.")
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
