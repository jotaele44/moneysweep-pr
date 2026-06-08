"""Ingest PR lobbying registry records into Canonical v1 ``lobbying_records.csv`` (WS-H).

Source surface: the committed reference seed
``data/reference/pr_lobbying_records.csv`` — a small set of well-documented public
Puerto Rico lobbying-registry registrations (firm + client). ``lobbyist_entity``
and ``client_entity`` resolve to existing canonical entities via the shared
resolver. Evidence-first: one accepted evidence row per record. Records describe
registry membership only (neutral, per ``docs/CLAIM_LANGUAGE_POLICY.md``).

Lobbying records are the basis for ``LOBBIES_FOR`` edges (lobbyist firm -> client),
which ``build_edges.py`` derives from ``lobbying_records.csv``.

Roadmap: WS-H, tasks T109-T122 (seed subset). Stdlib only.

CLI::

    python scripts/ingest_lobbying.py            # write lobbying_records + evidence
    python scripts/ingest_lobbying.py --check     # summarize without writing
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

from contract_sweeper.runtime.canonical_ids import lobbying_id
from scripts.build_edges import build_resolver, resolve
from scripts.build_evidence import Evidence, make_evidence, merge_evidence

REPO_ROOT = Path(__file__).resolve().parents[1]
LOBBYING_SOURCE = "data/reference/pr_lobbying_records.csv"
LOBBYING_OUT = "data/canonical_v1/lobbying_records.csv"
EVIDENCE_OUT = "data/canonical_v1/evidence.csv"
MANIFEST_OUT = "data/manifests/canonical_v1/lobbying_records.json"
SOURCE_NAME = "PR Lobbying Registry (reference seed)"

VALID_JURISDICTIONS = {"PR", "federal"}
VALID_FILING_TYPES = {"LDA", "PR_cabildero"}

LOBBYING_COLUMNS = [
    "lobbying_record_id",
    "jurisdiction",
    "registration_number",
    "period",
    "lobbyist_entity_id",
    "client_entity_id",
    "authorized_personnel",
    "subject_matter",
    "amount",
    "currency",
    "filing_type",
    "confidence",
    "evidence_id",
    "review_status",
    "notes",
]


def build_rows(root: Path | None = None) -> dict[str, Any]:
    """Build lobbying rows (firm/client resolved) + evidence + skip report."""
    root = root or REPO_ROOT
    resolver = build_resolver(root)
    rows: list[dict[str, Any]] = []
    evidence_rows: list[Evidence] = []
    skipped: list[dict[str, str]] = []
    seen: set[str] = set()

    with (root / LOBBYING_SOURCE).open(newline="", encoding="utf-8") as fh:
        for i, rec in enumerate(csv.DictReader(fh), start=2):
            jurisdiction = (rec.get("jurisdiction") or "").strip()
            filing = (rec.get("filing_type") or "").strip()
            reg = (rec.get("registration_number") or "").strip()
            period = (rec.get("period") or "").strip()
            reason = None
            if jurisdiction not in VALID_JURISDICTIONS:
                reason = f"invalid jurisdiction {jurisdiction!r}"
            elif filing not in VALID_FILING_TYPES:
                reason = f"invalid filing_type {filing!r}"
            if reason:
                skipped.append({"row": str(i), "reason": reason})
                continue

            lobbyist = (rec.get("lobbyist_entity") or "").strip()
            client = (rec.get("client_entity") or "").strip()
            lobbyist_id = resolve(resolver, "Entity", lobbyist) if lobbyist else ""
            client_id = resolve(resolver, "Entity", client) if client else ""

            lid = lobbying_id(jurisdiction, reg or str(i), period)
            if lid in seen:
                continue
            seen.add(lid)
            ev = make_evidence(
                source_type=(rec.get("source_type") or "registry").strip(),
                source_name=SOURCE_NAME,
                source_path_or_url=LOBBYING_SOURCE,
                page_or_line_ref=f"row {i}",
                claim=(rec.get("claim") or f"{lobbyist} registered lobbyist for {client}").strip(),
                extraction_method=(rec.get("extraction_method") or "manual").strip(),
                evidence_tier=(rec.get("evidence_tier") or "").strip() or None,
                review_status="accepted",
            )
            evidence_rows.append(ev)
            rows.append(
                {
                    "lobbying_record_id": lid,
                    "jurisdiction": jurisdiction,
                    "registration_number": reg,
                    "period": period,
                    "lobbyist_entity_id": lobbyist_id or "",
                    "client_entity_id": client_id or "",
                    "authorized_personnel": (rec.get("authorized_personnel") or "").strip(),
                    "subject_matter": (rec.get("subject_matter") or "").strip(),
                    "amount": (rec.get("amount") or "").strip(),
                    "currency": (rec.get("currency") or "").strip(),
                    "filing_type": filing,
                    "confidence": ev.confidence,
                    "evidence_id": ev.evidence_id,
                    "review_status": "accepted",
                    "notes": f"lobbyist={lobbyist}; client={client}",
                }
            )
    return {"lobbying_rows": rows, "evidence_rows": evidence_rows, "skipped": skipped}


def check(rows: list[dict[str, Any]]) -> list[str]:
    problems: list[str] = []
    if not rows:
        problems.append("no lobbying rows produced")
    ids = [r["lobbying_record_id"] for r in rows]
    if len(set(ids)) != len(ids):
        problems.append("duplicate lobbying_record_id values present")
    if any(r["jurisdiction"] not in VALID_JURISDICTIONS for r in rows):
        problems.append("invalid jurisdiction present")
    if any(r["filing_type"] not in VALID_FILING_TYPES for r in rows):
        problems.append("invalid filing_type present")
    return problems


def _write(rows: list[dict[str, Any]], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=LOBBYING_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def ingest(root: Path | None = None) -> dict[str, Any]:
    root = root or REPO_ROOT
    built = build_rows(root)
    rows, evidence_rows = built["lobbying_rows"], built["evidence_rows"]
    problems = check(rows)
    if problems:
        raise ValueError("lobbying ingest check failed: " + "; ".join(problems))
    _write(rows, root / LOBBYING_OUT)
    evidence_manifest = merge_evidence(root / EVIDENCE_OUT, evidence_rows)
    manifest = {
        "producer_script": "scripts/ingest_lobbying.py",
        "producer_phase": "CANONICAL_V1_LOBBYING_INGEST",
        "source_inputs": [LOBBYING_SOURCE],
        "row_count": len(rows),
        "with_lobbyist": sum(1 for r in rows if r["lobbyist_entity_id"]),
        "with_client": sum(1 for r in rows if r["client_entity_id"]),
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
    parser = argparse.ArgumentParser(description="Ingest PR lobbying records into canonical_v1.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    if args.check:
        built = build_rows(root)
        rows = built["lobbying_rows"]
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
