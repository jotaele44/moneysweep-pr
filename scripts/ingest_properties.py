"""Ingest PR public properties/assets into Canonical v1 ``properties.csv`` (WS-K).

Source surface: the committed reference seed
``data/reference/pr_properties.csv`` — a small set of well-documented public PR
concession/facility assets. Each ``owner_entity`` resolves to an existing canonical
entity and ``municipality`` to an existing municipality via the shared resolver.
Evidence-first: one accepted evidence row per property. Described neutrally as
public infrastructure assets (claim-language compliant).

Properties are the basis for ``LOCATED_IN`` edges (property -> municipality),
which ``build_edges.py`` derives from ``properties.csv``.

Roadmap: WS-K, tasks T150-T158 (seed subset). Stdlib only.

CLI::

    python scripts/ingest_properties.py            # write properties + evidence
    python scripts/ingest_properties.py --check     # summarize without writing
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

from moneysweep.runtime.canonical_ids import property_id
from scripts.build_edges import build_resolver, resolve
from scripts.build_evidence import Evidence, make_evidence, merge_evidence

REPO_ROOT = Path(__file__).resolve().parents[1]
PROPERTIES_SOURCE = "data/reference/pr_properties.csv"
PROPERTIES_OUT = "data/canonical_v1/properties.csv"
EVIDENCE_OUT = "data/canonical_v1/evidence.csv"
MANIFEST_OUT = "data/manifests/canonical_v1/properties.json"
SOURCE_NAME = "PR Public Properties (reference seed)"

VALID_TYPES = {"hotel", "land", "concession", "facility", "other"}

PROPERTY_COLUMNS = [
    "property_id",
    "property_name",
    "property_type",
    "owner_entity_id",
    "municipality_id",
    "address",
    "parcel_or_concession_id",
    "value",
    "currency",
    "confidence",
    "evidence_id",
    "review_status",
    "notes",
]


def build_rows(root: Path | None = None) -> dict[str, Any]:
    """Build property rows (owner resolved) + evidence + skip report."""
    root = root or REPO_ROOT
    resolver = build_resolver(root)
    rows: list[dict[str, Any]] = []
    evidence_rows: list[Evidence] = []
    skipped: list[dict[str, str]] = []
    seen: set[str] = set()

    with (root / PROPERTIES_SOURCE).open(newline="", encoding="utf-8") as fh:
        for i, rec in enumerate(csv.DictReader(fh), start=2):
            name = (rec.get("property_name") or "").strip()
            ptype = (rec.get("property_type") or "").strip()
            owner = (rec.get("owner_entity") or "").strip()
            reason = None
            if not name or ptype not in VALID_TYPES:
                reason = f"missing name or invalid property_type {ptype!r}"
            owner_id = resolve(resolver, "Entity", owner) if (not reason and owner) else ""
            if not reason and owner and owner_id is None:
                reason = f"unresolved owner_entity {owner!r}"
            if reason:
                skipped.append({"row": str(i), "reason": reason})
                continue

            muni = (rec.get("municipality") or "").strip()
            muni_id = resolve(resolver, "Municipality", muni) if muni else ""

            pid = property_id(name, owner)
            if pid in seen:
                continue
            seen.add(pid)
            ev = make_evidence(
                source_type=(rec.get("source_type") or "web").strip(),
                source_name=SOURCE_NAME,
                source_path_or_url=PROPERTIES_SOURCE,
                page_or_line_ref=f"row {i}",
                claim=(rec.get("claim") or f"{name} ({ptype}) owned by {owner}").strip(),
                extraction_method=(rec.get("extraction_method") or "manual").strip(),
                evidence_tier=(rec.get("evidence_tier") or "").strip() or None,
                review_status="accepted",
            )
            evidence_rows.append(ev)
            rows.append(
                {
                    "property_id": pid,
                    "property_name": name,
                    "property_type": ptype,
                    "owner_entity_id": owner_id or "",
                    "municipality_id": muni_id or "",
                    "address": (rec.get("address") or "").strip(),
                    "parcel_or_concession_id": (rec.get("parcel_or_concession_id") or "").strip(),
                    "value": (rec.get("value") or "").strip(),
                    "currency": (rec.get("currency") or "").strip(),
                    "confidence": ev.confidence,
                    "evidence_id": ev.evidence_id,
                    "review_status": "accepted",
                    "notes": f"owner={owner}" if owner else "",
                }
            )
    return {"property_rows": rows, "evidence_rows": evidence_rows, "skipped": skipped}


def check(rows: list[dict[str, Any]]) -> list[str]:
    problems: list[str] = []
    if not rows:
        problems.append("no property rows produced")
    ids = [r["property_id"] for r in rows]
    if len(set(ids)) != len(ids):
        problems.append("duplicate property_id values present")
    if any(r["property_type"] not in VALID_TYPES for r in rows):
        problems.append("invalid property_type present")
    return problems


def _write(rows: list[dict[str, Any]], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=PROPERTY_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def ingest(root: Path | None = None) -> dict[str, Any]:
    root = root or REPO_ROOT
    built = build_rows(root)
    rows, evidence_rows = built["property_rows"], built["evidence_rows"]
    problems = check(rows)
    if problems:
        raise ValueError("property ingest check failed: " + "; ".join(problems))
    _write(rows, root / PROPERTIES_OUT)
    evidence_manifest = merge_evidence(root / EVIDENCE_OUT, evidence_rows)
    type_counts: dict[str, int] = {}
    for r in rows:
        type_counts[r["property_type"]] = type_counts.get(r["property_type"], 0) + 1
    manifest = {
        "producer_script": "scripts/ingest_properties.py",
        "producer_phase": "CANONICAL_V1_PROPERTIES_INGEST",
        "source_inputs": [PROPERTIES_SOURCE],
        "row_count": len(rows),
        "property_type_counts": type_counts,
        "with_municipality": sum(1 for r in rows if r["municipality_id"]),
        "skipped_count": len(built["skipped"]),
        "skipped": built["skipped"],
        "evidence_rows_added": len(evidence_rows),
        "evidence_table_rows": evidence_manifest["row_count"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    manifest_path = root / MANIFEST_OUT
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ingest PR public properties into canonical_v1.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    if args.check:
        built = build_rows(root)
        rows = built["property_rows"]
        problems = check(rows)
        print(
            json.dumps(
                {
                    "ok": not problems,
                    "row_count": len(rows),
                    "skipped": len(built["skipped"]),
                    "problems": problems,
                },
                indent=2,
            )
        )
        return 0 if not problems else 1
    print(json.dumps(ingest(root), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
