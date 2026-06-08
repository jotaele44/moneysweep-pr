"""Ingest PR public funding sources into Canonical v1 ``funding_sources.csv`` (WS-I).

Source surface: the committed reference seed
``data/reference/pr_funding_sources.csv`` — a small set of well-documented public
federal programs funding Puerto Rico recovery/infrastructure. Each ``program`` is
from the schema enum (FEMA / HUD / EPA / DOE / CDBG-DR / ARPA). Evidence-first: one
accepted Tier-T2 evidence row per funding source. No entity resolution required —
the administering federal agency is optional and federal agencies are not in the
canonical entity set, so ``administering_entity_id`` is left blank.

Funding sources are the target of ``FUNDED_BY`` edges (project -> funding_source),
which ``build_edges.py`` derives from a funding-links seed.

Roadmap: WS-I, tasks T123-T134 (seed subset). Stdlib only.

CLI::

    python scripts/ingest_funding_sources.py            # write funding_sources + evidence
    python scripts/ingest_funding_sources.py --check     # summarize without writing
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

from contract_sweeper.runtime.canonical_ids import funding_id
from scripts.build_evidence import Evidence, make_evidence, merge_evidence

REPO_ROOT = Path(__file__).resolve().parents[1]
FUNDING_SOURCE = "data/reference/pr_funding_sources.csv"
FUNDING_OUT = "data/canonical_v1/funding_sources.csv"
EVIDENCE_OUT = "data/canonical_v1/evidence.csv"
MANIFEST_OUT = "data/manifests/canonical_v1/funding_sources.json"
SOURCE_NAME = "PR Public Funding Sources (reference seed)"

VALID_PROGRAMS = {"FEMA", "HUD", "EPA", "DOE", "CDBG-DR", "ARPA", "other"}

FUNDING_COLUMNS = [
    "funding_source_id",
    "program",
    "program_year",
    "administering_entity_id",
    "jurisdiction",
    "total_allocation",
    "currency",
    "confidence",
    "evidence_id",
    "review_status",
    "notes",
]


def build_rows(root: Path | None = None) -> dict[str, Any]:
    """Return funding rows + evidence + skip report from the reference seed."""
    root = root or REPO_ROOT
    funding_rows: list[dict[str, Any]] = []
    evidence_rows: list[Evidence] = []
    skipped: list[dict[str, str]] = []
    seen: set[str] = set()

    with (root / FUNDING_SOURCE).open(newline="", encoding="utf-8") as fh:
        for i, rec in enumerate(csv.DictReader(fh), start=2):
            program = (rec.get("program") or "").strip()
            year = (rec.get("program_year") or "").strip()
            name = (rec.get("name") or "").strip()
            if program not in VALID_PROGRAMS:
                skipped.append({"row": str(i), "reason": f"invalid program {program!r}"})
                continue
            fid = funding_id(program, year or name)
            if fid in seen:
                continue
            seen.add(fid)
            ev = make_evidence(
                source_type="registry",
                source_name=SOURCE_NAME,
                source_path_or_url=FUNDING_SOURCE,
                page_or_line_ref=f"row {i}",
                claim=(rec.get("description") or f"{name} ({program})").strip(),
                extraction_method="manual",
                evidence_tier="T2",
                review_status="accepted",
            )
            evidence_rows.append(ev)
            funding_rows.append(
                {
                    "funding_source_id": fid,
                    "program": program,
                    "program_year": year,
                    "administering_entity_id": "",
                    "jurisdiction": (rec.get("jurisdiction") or "").strip(),
                    "total_allocation": (rec.get("total_allocation") or "").strip(),
                    "currency": (rec.get("currency") or "").strip(),
                    "confidence": ev.confidence,
                    "evidence_id": ev.evidence_id,
                    "review_status": "accepted",
                    "notes": f"name={name}" if name else "",
                }
            )
    return {"funding_rows": funding_rows, "evidence_rows": evidence_rows, "skipped": skipped}


def check(rows: list[dict[str, Any]]) -> list[str]:
    problems: list[str] = []
    if not rows:
        problems.append("no funding rows produced")
    ids = [r["funding_source_id"] for r in rows]
    if len(set(ids)) != len(ids):
        problems.append("duplicate funding_source_id values present")
    if any(r["program"] not in VALID_PROGRAMS for r in rows):
        problems.append("invalid program present")
    return problems


def _write(rows: list[dict[str, Any]], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=FUNDING_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def ingest(root: Path | None = None) -> dict[str, Any]:
    root = root or REPO_ROOT
    built = build_rows(root)
    rows, evidence_rows = built["funding_rows"], built["evidence_rows"]
    problems = check(rows)
    if problems:
        raise ValueError("funding ingest check failed: " + "; ".join(problems))
    _write(rows, root / FUNDING_OUT)
    evidence_manifest = merge_evidence(root / EVIDENCE_OUT, evidence_rows)
    program_counts: dict[str, int] = {}
    for r in rows:
        program_counts[r["program"]] = program_counts.get(r["program"], 0) + 1
    manifest = {
        "producer_script": "scripts/ingest_funding_sources.py",
        "producer_phase": "CANONICAL_V1_FUNDING_INGEST",
        "source_inputs": [FUNDING_SOURCE],
        "row_count": len(rows),
        "program_counts": program_counts,
        "evidence_rows_added": len(evidence_rows),
        "evidence_table_rows": evidence_manifest["row_count"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    manifest_path = root / MANIFEST_OUT
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ingest PR funding sources into canonical_v1.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    if args.check:
        built = build_rows(root)
        rows = built["funding_rows"]
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
