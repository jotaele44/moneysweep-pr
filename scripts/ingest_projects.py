"""Ingest PR public infrastructure projects into Canonical v1 ``projects.csv`` (WS-G).

Source surface: the committed reference seed
``data/reference/pr_infrastructure_projects.csv`` — a small set of well-documented
public PR infrastructure programs and P3 concessions. Each project's ``lead_entity``
resolves to an existing canonical entity (and optional ``municipality`` to an
existing municipality node) via the shared resolver in ``scripts/build_edges.py``.
Evidence-first: one accepted Tier-T2 evidence row per project. Only projects whose
lead entity resolves are written (``lead_entity_id`` references must not dangle);
others are reported as skips.

Projects are the anchor for ``LOCATED_IN`` (project -> municipality) and for
operator relationships (e.g. LUMA / Genera / Metropistas) that ``build_edges.py``
derives, so an operator edge attaches to the project rather than to an agency.

Roadmap: WS-G, tasks T97-T108 (seed subset). Stdlib only.

CLI::

    python scripts/ingest_projects.py            # write projects + evidence
    python scripts/ingest_projects.py --check     # summarize without writing
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

from contract_sweeper.runtime.canonical_ids import project_id
from scripts.build_edges import build_resolver, resolve
from scripts.build_evidence import Evidence, make_evidence, merge_evidence

REPO_ROOT = Path(__file__).resolve().parents[1]
PROJECTS_SOURCE = "data/reference/pr_infrastructure_projects.csv"
PROJECTS_OUT = "data/canonical_v1/projects.csv"
EVIDENCE_OUT = "data/canonical_v1/evidence.csv"
MANIFEST_OUT = "data/manifests/canonical_v1/projects.json"
SOURCE_NAME = "PR Infrastructure Projects (reference seed)"

VALID_TYPES = {"infrastructure", "recovery", "ppp", "real_estate", "other"}

PROJECT_COLUMNS = [
    "project_id", "project_name", "project_number", "project_type",
    "lead_entity_id", "municipality_id", "funding_source_id", "total_value",
    "currency", "status", "start_date", "end_date", "confidence",
    "evidence_id", "review_status", "notes",
]


def build_rows(root: Path | None = None) -> dict[str, Any]:
    """Build project rows (lead entity resolved) + evidence + skip report."""
    root = root or REPO_ROOT
    resolver = build_resolver(root)
    project_rows: list[dict[str, Any]] = []
    evidence_rows: list[Evidence] = []
    skipped: list[dict[str, str]] = []
    seen: set[str] = set()

    with (root / PROJECTS_SOURCE).open(newline="", encoding="utf-8") as fh:
        for i, rec in enumerate(csv.DictReader(fh), start=2):
            name = (rec.get("project_name") or "").strip()
            ptype = (rec.get("project_type") or "").strip()
            number = (rec.get("project_number") or "").strip()
            lead = (rec.get("lead_entity") or "").strip()
            muni = (rec.get("municipality") or "").strip()
            reason = None
            if not name or ptype not in VALID_TYPES:
                reason = f"missing name or invalid project_type {ptype!r}"
            lead_id = resolve(resolver, "Entity", lead) if not reason else None
            if not reason and lead_id is None:
                reason = f"unresolved lead_entity {lead!r}"
            if reason:
                skipped.append({"row": str(i), "reason": reason})
                continue
            muni_id = resolve(resolver, "Municipality", muni) if muni else ""

            pid = project_id(lead, number or name)
            if pid in seen:
                continue
            seen.add(pid)
            ev = make_evidence(
                source_type=(rec.get("source_type") or "web").strip(),
                source_name=SOURCE_NAME,
                source_path_or_url=PROJECTS_SOURCE,
                page_or_line_ref=f"row {i}",
                claim=(rec.get("claim") or f"{name} led by {lead}").strip(),
                extraction_method=(rec.get("extraction_method") or "manual").strip(),
                evidence_tier=(rec.get("evidence_tier") or "").strip() or None,
                review_status="accepted",
            )
            evidence_rows.append(ev)
            project_rows.append({
                "project_id": pid,
                "project_name": name,
                "project_number": number,
                "project_type": ptype,
                "lead_entity_id": lead_id,
                "municipality_id": muni_id or "",
                "funding_source_id": "",
                "total_value": (rec.get("total_value") or "").strip(),
                "currency": (rec.get("currency") or "").strip(),
                "status": (rec.get("status") or "").strip(),
                "start_date": (rec.get("start_date") or "").strip(),
                "end_date": (rec.get("end_date") or "").strip(),
                "confidence": ev.confidence,
                "evidence_id": ev.evidence_id,
                "review_status": "accepted",
                "notes": f"lead={lead}",
            })
    return {"project_rows": project_rows, "evidence_rows": evidence_rows, "skipped": skipped}


def check(rows: list[dict[str, Any]]) -> list[str]:
    problems: list[str] = []
    if not rows:
        problems.append("no project rows produced")
    ids = [r["project_id"] for r in rows]
    if len(set(ids)) != len(ids):
        problems.append("duplicate project_id values present")
    if any(r["project_type"] not in VALID_TYPES for r in rows):
        problems.append("invalid project_type present")
    return problems


def _write(rows: list[dict[str, Any]], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=PROJECT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def ingest(root: Path | None = None) -> dict[str, Any]:
    root = root or REPO_ROOT
    built = build_rows(root)
    rows, evidence_rows = built["project_rows"], built["evidence_rows"]
    problems = check(rows)
    if problems:
        raise ValueError("project ingest check failed: " + "; ".join(problems))
    _write(rows, root / PROJECTS_OUT)
    evidence_manifest = merge_evidence(root / EVIDENCE_OUT, evidence_rows)
    type_counts: dict[str, int] = {}
    for r in rows:
        type_counts[r["project_type"]] = type_counts.get(r["project_type"], 0) + 1
    manifest = {
        "producer_script": "scripts/ingest_projects.py",
        "producer_phase": "CANONICAL_V1_PROJECTS_INGEST",
        "source_inputs": [PROJECTS_SOURCE],
        "row_count": len(rows),
        "project_type_counts": type_counts,
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
    parser = argparse.ArgumentParser(description="Ingest PR infrastructure projects into canonical_v1.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    if args.check:
        built = build_rows(root)
        rows = built["project_rows"]
        problems = check(rows)
        print(json.dumps({"ok": not problems, "row_count": len(rows),
                          "skipped": len(built["skipped"]), "problems": problems}, indent=2))
        return 0 if not problems else 1
    print(json.dumps(ingest(root), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
