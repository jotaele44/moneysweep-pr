"""Seed core PR public-money institutions into Canonical v1 ``entities.csv`` (WS-E).

No external entity dataset was supplied, so this ingests a small, curated, and
**indisputable** set of public institutions that the canonical model itself
already requires: the GO / COFINA / PREPA / PRASA / HTA debt issuers named in
the ``debt_class`` enum, the fiscal/oversight bodies (FOMB, AAFAF, P3 Authority,
GDB), and the privatized utility operators (LUMA, Genera, Metropistas). They are
the anchors that the people, debt, contracts, projects, and funding tables link
to.

Source surface: the committed reference file
``data/reference/pr_public_money_entities.csv`` (public, non-PII). Evidence-first:
one accepted Tier-T1 evidence row per entity, referenced by ``evidence_id``. This
is a deliberately conservative seed, not speculative expansion; richer entity
ingestion (lobbying firms, contractors, funds) follows once those source
surfaces are available.

Roadmap: WS-E, tasks T69-T82 (seed subset). Stdlib only.

CLI::

    python scripts/ingest_entities.py            # write entities + evidence
    python scripts/ingest_entities.py --check     # validate without writing
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

from contract_sweeper.runtime.canonical_ids import entity_id
from contract_sweeper.runtime.name_normalization import normalize_name
from scripts.build_evidence import Evidence, make_evidence, merge_evidence

REPO_ROOT = Path(__file__).resolve().parents[1]
REFERENCE = "data/reference/pr_public_money_entities.csv"
ENTITIES_OUT = "data/canonical_v1/entities.csv"
EVIDENCE_OUT = "data/canonical_v1/evidence.csv"
MANIFEST_OUT = "data/manifests/canonical_v1/entities.json"
SOURCE_NAME = "PR Public-Money Institutions (reference seed)"

VALID_TYPES = {"agency", "firm", "fund", "nonprofit", "utility", "other"}

ENTITY_COLUMNS = [
    "entity_id", "name", "normalized_name", "entity_type", "parent_entity_id",
    "jurisdiction", "registry_ids", "confidence", "evidence_id", "review_status", "notes",
]


def build_rows(root: Path | None = None) -> tuple[list[dict[str, Any]], list[Evidence]]:
    """Return (entity rows, evidence rows) from the reference seed."""
    root = root or REPO_ROOT
    entity_rows: list[dict[str, Any]] = []
    evidence_rows: list[Evidence] = []
    with (root / REFERENCE).open(newline="", encoding="utf-8") as fh:
        for i, ref in enumerate(csv.DictReader(fh), start=2):  # line 1 is header
            name = (ref.get("name") or "").strip()
            etype = (ref.get("entity_type") or "").strip()
            if not name or etype not in VALID_TYPES:
                continue
            aliases = (ref.get("aliases") or "").strip()
            desc = (ref.get("description") or "").strip()
            ev = make_evidence(
                source_type="registry",
                source_name=SOURCE_NAME,
                source_path_or_url=REFERENCE,
                page_or_line_ref=f"row {i}",
                claim=f"'{name}' is a Puerto Rico public-money institution ({etype}). {desc}".strip(),
                extraction_method="manual",
                review_status="accepted",
            )
            evidence_rows.append(ev)
            entity_rows.append({
                "entity_id": entity_id(name),
                "name": name,
                "normalized_name": normalize_name(name),
                "entity_type": etype,
                "parent_entity_id": "",
                "jurisdiction": (ref.get("jurisdiction") or "").strip(),
                "registry_ids": "",
                "confidence": ev.confidence,
                "evidence_id": ev.evidence_id,
                "review_status": "accepted",
                "notes": f"aliases={aliases}" if aliases else "",
            })
    return entity_rows, evidence_rows


def check(rows: list[dict[str, Any]]) -> list[str]:
    problems: list[str] = []
    if not rows:
        problems.append("no entity rows produced")
    ids = [r["entity_id"] for r in rows]
    if len(set(ids)) != len(ids):
        problems.append("duplicate entity_id values present")
    if any(r["entity_type"] not in VALID_TYPES for r in rows):
        problems.append("invalid entity_type present")
    return problems


def _write(rows: list[dict[str, Any]], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=ENTITY_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def ingest(root: Path | None = None) -> dict[str, Any]:
    root = root or REPO_ROOT
    rows, evidence_rows = build_rows(root)
    problems = check(rows)
    if problems:
        raise ValueError("entity seed check failed: " + "; ".join(problems))
    _write(rows, root / ENTITIES_OUT)
    evidence_manifest = merge_evidence(root / EVIDENCE_OUT, evidence_rows)
    manifest = {
        "producer_script": "scripts/ingest_entities.py",
        "producer_phase": "CANONICAL_V1_ENTITIES_SEED",
        "source_inputs": [REFERENCE],
        "row_count": len(rows),
        "evidence_rows_added": len(evidence_rows),
        "evidence_table_rows": evidence_manifest["row_count"],
        "entity_types": sorted({r["entity_type"] for r in rows}),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    manifest_path = root / MANIFEST_OUT
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seed PR public-money institutions into canonical_v1 entities.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    if args.check:
        rows, _ = build_rows(root)
        problems = check(rows)
        print(json.dumps({"ok": not problems, "row_count": len(rows), "problems": problems}, indent=2))
        return 0 if not problems else 1
    print(json.dumps(ingest(root), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
