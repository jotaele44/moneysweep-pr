"""Build the FOIA yield tracker (Gate ``foia``, item ``yield_tracking``).

Reconciles each open FOIA request against the live materialization gap it is
meant to close: one row per request from the priority queue, carrying the
records received so far, a yield status, and the still-unresolved gap (the
source's current blocker). Until a request is fulfilled and its source
materializes, the gap stays open — so this is the closure ledger for the FOIA
program.

Input:  ``reports/foia_priority_queue.csv`` (built by build_foia_tracker.py)
        + ``reports/source_registry_status.csv`` (live blocker notes)
Output: ``reports/foia_yield_tracking.csv`` + ``data/manifests/foia_yield_tracking.json``

Pure, deterministic, no network. Reuses the stdlib schema validator.

CLI::

    python scripts/build_foia_yield_tracking.py            # write the CSV + manifest
    python scripts/build_foia_yield_tracking.py --check     # validate without writing
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

from moneysweep.validation.canonical_v1_schema import validate_row

REPO_ROOT = Path(__file__).resolve().parents[1]

PRIORITY_QUEUE = "reports/foia_priority_queue.csv"
SOURCE_STATUS = "reports/source_registry_status.csv"
OUT = "reports/foia_yield_tracking.csv"
MANIFEST_OUT = "data/manifests/foia_yield_tracking.json"
SCHEMA = "schemas/foia_yield.schema.json"

# request_status -> yield_status for an as-yet-unfulfilled program.
YIELD_BY_REQUEST_STATUS = {
    "planned": "pending",
    "drafted": "pending",
    "submitted": "pending",
    "awaiting_response": "pending",
    "partial_yield": "partial",
    "fulfilled": "received",
    "denied": "no_response",
    "appealed": "pending",
}

COLUMNS = [
    "request_id",
    "target_source_id",
    "request_status",
    "records_received",
    "yield_status",
    "unresolved_gap",
    "evidence_tier",
    "confidence",
    "notes",
]


def _load_schema(root: Path) -> dict[str, Any]:
    return json.loads((root / SCHEMA).read_text(encoding="utf-8"))


def _read(root: Path, rel: str) -> list[dict[str, str]]:
    with (root / rel).open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _blocker_index(root: Path) -> dict[str, str]:
    """Map source_id -> (blocker_notes or pipeline_status) for the unresolved gap."""
    index: dict[str, str] = {}
    for r in _read(root, SOURCE_STATUS):
        note = (r.get("blocker_notes") or "").strip()
        if not note:
            note = f"pipeline_status={(r.get('pipeline_status') or 'unknown').strip()}"
        index[r["source_id"]] = note
    return index


def build_rows(root: Path | None = None) -> list[dict[str, Any]]:
    """Return one yield row per FOIA request."""
    root = root or REPO_ROOT
    blockers = _blocker_index(root)
    rows: list[dict[str, Any]] = []
    for req in _read(root, PRIORITY_QUEUE):
        source_id = req["target_source_id"]
        req_status = req["request_status"]
        gap = blockers.get(source_id) or f"source {source_id} unmaterialized"
        rows.append(
            {
                "request_id": req["request_id"],
                "target_source_id": source_id,
                "request_status": req_status,
                "records_received": 0,
                "yield_status": YIELD_BY_REQUEST_STATUS.get(req_status, "pending"),
                "unresolved_gap": gap,
                "evidence_tier": req.get("evidence_tier") or "T2",
                "confidence": float(req.get("confidence") or 0.0),
                "notes": "",
            }
        )
    return rows


def check(rows: list[dict[str, Any]], root: Path | None = None) -> list[str]:
    """Return a list of problems (empty == valid)."""
    root = root or REPO_ROOT
    problems: list[str] = []
    if not rows:
        problems.append("no FOIA yield rows produced")
    # one yield row per request, no duplicates
    ids = [r["request_id"] for r in rows]
    if len(set(ids)) != len(ids):
        problems.append("duplicate request_id values present")
    queue_ids = {r["request_id"] for r in _read(root, PRIORITY_QUEUE)}
    if set(ids) != queue_ids:
        problems.append("yield rows do not 1:1 match the priority queue requests")
    schema = _load_schema(root)
    for i, row in enumerate(rows, start=1):
        for msg in validate_row(row, schema):
            problems.append(f"row {i} ({row.get('request_id')}): {msg}")
    return problems


def _write(rows: list[dict[str, Any]], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def build(root: Path | None = None) -> dict[str, Any]:
    """Build, validate, and write the FOIA yield CSV + manifest."""
    root = root or REPO_ROOT
    rows = build_rows(root)
    problems = check(rows, root)
    if problems:
        raise ValueError("foia_yield_tracking check failed: " + "; ".join(problems))
    _write(rows, root / OUT)
    manifest = {
        "producer_script": "scripts/build_foia_yield_tracking.py",
        "producer_phase": "TOP_FORM_FOIA_YIELD_TRACKING",
        "schema": SCHEMA,
        "source_inputs": [PRIORITY_QUEUE, SOURCE_STATUS],
        "output": OUT,
        "row_count": len(rows),
        "open_gaps": sum(
            1 for r in rows if r["yield_status"] in ("pending", "partial", "no_response")
        ),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    manifest_path = root / MANIFEST_OUT
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the FOIA yield tracker.")
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
