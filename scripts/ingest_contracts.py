"""Ingest PR public contracts into Canonical v1 ``contracts.csv`` (WS-F).

Source surface: the committed reference seed
``data/reference/pr_public_contracts.csv`` — a small set of well-documented public
PR P3 agreements. Each contract's ``awarding_entity`` (required) resolves to an
existing canonical entity; ``contractor_entity`` and ``project`` resolve when
present. Evidence-first: one accepted Tier-T2 evidence row per contract.

Contracts are the basis for ``RECEIVES_CONTRACT`` edges (contractor -> contract),
which ``build_edges.py`` derives from ``contracts.csv``.

Roadmap: WS-F, tasks T83-T96 (seed subset). Stdlib only.

CLI::

    python scripts/ingest_contracts.py            # write contracts + evidence
    python scripts/ingest_contracts.py --check     # summarize without writing
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

from contract_sweeper.runtime.canonical_ids import contract_id
from scripts.build_edges import build_resolver, resolve
from scripts.build_evidence import Evidence, make_evidence, merge_evidence

REPO_ROOT = Path(__file__).resolve().parents[1]
CONTRACTS_SOURCE = "data/reference/pr_public_contracts.csv"
CONTRACTS_OUT = "data/canonical_v1/contracts.csv"
EVIDENCE_OUT = "data/canonical_v1/evidence.csv"
MANIFEST_OUT = "data/manifests/canonical_v1/contracts.json"
SOURCE_NAME = "PR Public Contracts (reference seed)"

VALID_STATUS = {"award", "amendment", "active", "completed", "terminated", "other"}

CONTRACT_COLUMNS = [
    "contract_id",
    "contract_number",
    "awarding_entity_id",
    "contractor_entity_id",
    "project_id",
    "service_type",
    "award_amount",
    "currency",
    "start_date",
    "end_date",
    "status",
    "confidence",
    "evidence_id",
    "review_status",
    "notes",
]


def build_rows(root: Path | None = None) -> dict[str, Any]:
    """Build contract rows (awarding entity resolved) + evidence + skip report."""
    root = root or REPO_ROOT
    resolver = build_resolver(root)
    contract_rows: list[dict[str, Any]] = []
    evidence_rows: list[Evidence] = []
    skipped: list[dict[str, str]] = []
    seen: set[str] = set()

    with (root / CONTRACTS_SOURCE).open(newline="", encoding="utf-8") as fh:
        for i, rec in enumerate(csv.DictReader(fh), start=2):
            number = (rec.get("contract_number") or "").strip()
            awarding = (rec.get("awarding_entity") or "").strip()
            status = (rec.get("status") or "").strip()
            reason = None
            if status and status not in VALID_STATUS:
                reason = f"invalid status {status!r}"
            awarding_id = resolve(resolver, "Entity", awarding) if not reason else None
            if not reason and awarding_id is None:
                reason = f"unresolved awarding_entity {awarding!r}"
            if reason:
                skipped.append({"row": str(i), "reason": reason})
                continue

            contractor = (rec.get("contractor_entity") or "").strip()
            project = (rec.get("project") or "").strip()
            contractor_id = resolve(resolver, "Entity", contractor) if contractor else ""
            project_id_val = resolve(resolver, "Project", project) if project else ""

            cid = contract_id(awarding, number or rec.get("project") or str(i))
            if cid in seen:
                continue
            seen.add(cid)
            ev = make_evidence(
                source_type=(rec.get("source_type") or "web").strip(),
                source_name=SOURCE_NAME,
                source_path_or_url=CONTRACTS_SOURCE,
                page_or_line_ref=f"row {i}",
                claim=(
                    rec.get("claim") or f"{awarding} awarded a contract to {contractor}"
                ).strip(),
                extraction_method=(rec.get("extraction_method") or "manual").strip(),
                evidence_tier=(rec.get("evidence_tier") or "").strip() or None,
                review_status="accepted",
            )
            evidence_rows.append(ev)
            contract_rows.append(
                {
                    "contract_id": cid,
                    "contract_number": number,
                    "awarding_entity_id": awarding_id,
                    "contractor_entity_id": contractor_id or "",
                    "project_id": project_id_val or "",
                    "service_type": (rec.get("service_type") or "").strip(),
                    "award_amount": (rec.get("award_amount") or "").strip(),
                    "currency": (rec.get("currency") or "USD").strip(),
                    "start_date": (rec.get("start_date") or "").strip(),
                    "end_date": (rec.get("end_date") or "").strip(),
                    "status": status,
                    "confidence": ev.confidence,
                    "evidence_id": ev.evidence_id,
                    "review_status": "accepted",
                    "notes": f"awarding={awarding}; contractor={contractor}",
                }
            )
    return {"contract_rows": contract_rows, "evidence_rows": evidence_rows, "skipped": skipped}


def check(rows: list[dict[str, Any]]) -> list[str]:
    problems: list[str] = []
    if not rows:
        problems.append("no contract rows produced")
    ids = [r["contract_id"] for r in rows]
    if len(set(ids)) != len(ids):
        problems.append("duplicate contract_id values present")
    if any(r["status"] and r["status"] not in VALID_STATUS for r in rows):
        problems.append("invalid status present")
    return problems


def _write(rows: list[dict[str, Any]], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CONTRACT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def ingest(root: Path | None = None) -> dict[str, Any]:
    root = root or REPO_ROOT
    built = build_rows(root)
    rows, evidence_rows = built["contract_rows"], built["evidence_rows"]
    problems = check(rows)
    if problems:
        raise ValueError("contract ingest check failed: " + "; ".join(problems))
    _write(rows, root / CONTRACTS_OUT)
    evidence_manifest = merge_evidence(root / EVIDENCE_OUT, evidence_rows)
    manifest = {
        "producer_script": "scripts/ingest_contracts.py",
        "producer_phase": "CANONICAL_V1_CONTRACTS_INGEST",
        "source_inputs": [CONTRACTS_SOURCE],
        "row_count": len(rows),
        "with_contractor": sum(1 for r in rows if r["contractor_entity_id"]),
        "with_project": sum(1 for r in rows if r["project_id"]),
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
    parser = argparse.ArgumentParser(description="Ingest PR public contracts into canonical_v1.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    if args.check:
        built = build_rows(root)
        rows = built["contract_rows"]
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
