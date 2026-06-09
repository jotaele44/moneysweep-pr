"""Ingest person-to-institution roles into Canonical v1 ``roles.csv`` (WS-L).

Resolves a roles source (person name + entity name + position) against existing
``people.csv`` and ``entities.csv`` nodes, emitting a role row only when both
endpoints resolve and the role is backed by an evidence row. The first source is
the public, indisputable PROMESA Financial Oversight and Management Board
membership (the seven 2016 appointees), all of which are already accepted people
nodes. Neutral, claim-language-compliant; no accusatory content.

Roles are the basis for ``HOLDS_ROLE_IN`` edges, which ``build_edges.py`` derives
from ``roles.csv`` (so ``edges.csv`` stays single-writer).

Roadmap: WS-L, tasks T163-T166. Stdlib only.

CLI::

    python scripts/ingest_roles.py            # write roles + evidence
    python scripts/ingest_roles.py --check     # resolve + report without writing
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
from scripts.build_edges import build_resolver, resolve
from scripts.build_evidence import Evidence, make_evidence, merge_evidence

REPO_ROOT = Path(__file__).resolve().parents[1]
ROLES_SOURCE = "data/reference/fomb_board_roles.csv"
ROLES_OUT = "data/canonical_v1/roles.csv"
EVIDENCE_OUT = "data/canonical_v1/evidence.csv"
MANIFEST_OUT = "data/manifests/canonical_v1/roles.json"
SOURCE_NAME = "FOMB Board Membership (reference seed)"

VALID_CATEGORIES = {"executive", "board", "officer", "agent", "advisor", "lobbyist", "other"}

ROLES_COLUMNS = [
    "role_id",
    "person_id",
    "entity_id",
    "role_title",
    "role_category",
    "start_date",
    "end_date",
    "current",
    "confidence",
    "evidence_id",
    "review_status",
    "notes",
]


def role_id(person_id: str | None, entity_id: str | None, role_title: str) -> str:
    """Deterministic role id from (person, entity, title)."""
    return f"role_{name_hash(f'{person_id}|{entity_id}|{role_title}')}"


def build_records(root: Path | None = None) -> dict[str, Any]:
    root = root or REPO_ROOT
    resolver = build_resolver(root)
    role_rows: list[dict[str, Any]] = []
    evidence_rows: list[Evidence] = []
    skipped: list[dict[str, str]] = []
    seen: set[str] = set()

    with (root / ROLES_SOURCE).open(newline="", encoding="utf-8") as fh:
        for i, rel in enumerate(csv.DictReader(fh), start=2):
            pname = (rel.get("person_name") or "").strip()
            ename = (rel.get("entity_name") or "").strip()
            category = (rel.get("role_category") or "other").strip()
            pid = resolve(resolver, "Person", pname)
            eid = resolve(resolver, "Entity", ename)
            reason = None
            if category not in VALID_CATEGORIES:
                reason = f"invalid role_category {category!r}"
            elif pid is None:
                reason = f"unresolved person {pname!r}"
            elif eid is None:
                reason = f"unresolved entity {ename!r}"
            if reason:
                skipped.append({"row": str(i), "reason": reason})
                continue

            title = (rel.get("role_title") or "").strip()
            ev = make_evidence(
                source_type=(rel.get("source_type") or "web").strip(),
                source_name=SOURCE_NAME,
                source_path_or_url=ROLES_SOURCE,
                page_or_line_ref=f"row {i}",
                claim=(rel.get("claim") or f"{pname} holds role in {ename}").strip(),
                extraction_method=(rel.get("extraction_method") or "manual").strip(),
                evidence_tier=(rel.get("evidence_tier") or "").strip() or None,
                review_status="accepted",
            )
            rid = role_id(pid, eid, title)
            if rid in seen:
                continue
            seen.add(rid)
            evidence_rows.append(ev)
            role_rows.append(
                {
                    "role_id": rid,
                    "person_id": pid,
                    "entity_id": eid,
                    "role_title": title,
                    "role_category": category,
                    "start_date": (rel.get("start_date") or "").strip(),
                    "end_date": (rel.get("end_date") or "").strip(),
                    "current": (rel.get("current") or "").strip().lower(),
                    "confidence": ev.confidence,
                    "evidence_id": ev.evidence_id,
                    "review_status": "accepted",
                    "notes": "",
                }
            )

    return {"role_rows": role_rows, "evidence_rows": evidence_rows, "skipped": skipped}


def _write(rows: list[dict[str, Any]], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=ROLES_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def ingest(root: Path | None = None) -> dict[str, Any]:
    root = root or REPO_ROOT
    built = build_records(root)
    _write(built["role_rows"], root / ROLES_OUT)
    evidence_manifest = merge_evidence(root / EVIDENCE_OUT, built["evidence_rows"])
    manifest = {
        "producer_script": "scripts/ingest_roles.py",
        "producer_phase": "CANONICAL_V1_ROLES_INGEST",
        "source_inputs": [ROLES_SOURCE],
        "row_count": len(built["role_rows"]),
        "skipped_count": len(built["skipped"]),
        "skipped": built["skipped"],
        "evidence_table_rows": evidence_manifest["row_count"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    manifest_path = root / MANIFEST_OUT
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ingest person-entity roles into canonical_v1.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    if args.check:
        built = build_records(root)
        print(
            json.dumps(
                {"row_count": len(built["role_rows"]), "skipped": built["skipped"]}, indent=2
            )
        )
        return 0
    print(json.dumps(ingest(root), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
