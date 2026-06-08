"""Ingest the 78 Puerto Rico municipalities into Canonical v1 ``municipalities.csv``.

Source surface: the committed reference dataset
``data/reference/pr_municipalities.csv`` (public, non-PII). This is the first
*populated* canonical_v1 table and the geographic anchor for ``LOCATED_IN``
edges. It is evidence-first: one accepted ``evidence.csv`` row (Tier T1,
registry, manual) is created per municipality before the node row, and the
node references it via ``evidence_id``.

Roadmap: WS-K, tasks T147-T149. Stdlib only.

CLI::

    python scripts/ingest_municipalities.py            # writes the canonical tables
    python scripts/ingest_municipalities.py --check     # validate coverage only
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

from contract_sweeper.runtime.canonical_ids import municipality_id
from contract_sweeper.runtime.name_normalization import normalize_name
from scripts.build_evidence import Evidence, make_evidence, merge_evidence

REPO_ROOT = Path(__file__).resolve().parents[1]
REFERENCE = "data/reference/pr_municipalities.csv"
MUNI_OUT = "data/canonical_v1/municipalities.csv"
EVIDENCE_OUT = "data/canonical_v1/evidence.csv"
MANIFEST_OUT = "data/manifests/canonical_v1/municipalities.json"
SOURCE_NAME = "data/reference/pr_municipalities.csv"
EXPECTED_COUNT = 78

MUNI_COLUMNS = [
    "municipality_id",
    "name",
    "normalized_name",
    "region",
    "county_fips",
    "aliases",
    "confidence",
    "evidence_id",
    "review_status",
    "notes",
]


def _aliases(ref_row: dict[str, str]) -> str:
    """Merge the reference aliases with the Spanish canonical name (de-duped)."""
    parts: list[str] = []
    for piece in (ref_row.get("aliases") or "").split("|"):
        piece = piece.strip()
        if piece and piece not in parts:
            parts.append(piece)
    es = (ref_row.get("canonical_name_es") or "").strip()
    if es and es not in parts:
        parts.append(es)
    return "|".join(parts)


def build_rows(root: Path | None = None) -> tuple[list[dict[str, Any]], list[Evidence]]:
    """Return (municipality rows, evidence rows) built from the reference dataset."""
    root = root or REPO_ROOT
    muni_rows: list[dict[str, Any]] = []
    evidence_rows: list[Evidence] = []
    with (root / REFERENCE).open(newline="", encoding="utf-8") as fh:
        for i, ref in enumerate(csv.DictReader(fh), start=2):  # line 1 is header
            name = (ref.get("canonical_name") or "").strip()
            if not name:
                continue
            county_fips = (ref.get("county_fips") or "").strip()
            claim = f"Puerto Rico municipality '{name}' (county FIPS {county_fips})"
            ev = make_evidence(
                source_type="registry",
                source_name=SOURCE_NAME,
                source_path_or_url=REFERENCE,
                page_or_line_ref=f"row {i}",
                claim=claim,
                extraction_method="manual",
                review_status="accepted",
            )
            evidence_rows.append(ev)
            muni_rows.append(
                {
                    "municipality_id": municipality_id(name),
                    "name": name,
                    "normalized_name": normalize_name(name),
                    "region": (ref.get("region") or "").strip(),
                    "county_fips": county_fips,
                    "aliases": _aliases(ref),
                    "confidence": ev.confidence,
                    "evidence_id": ev.evidence_id,
                    "review_status": "accepted",
                    "notes": "",
                }
            )
    return muni_rows, evidence_rows


def write_municipalities(rows: list[dict[str, Any]], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=MUNI_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def check_coverage(rows: list[dict[str, Any]]) -> list[str]:
    """Return a list of coverage problems (empty == full, valid coverage)."""
    problems: list[str] = []
    if len(rows) != EXPECTED_COUNT:
        problems.append(f"expected {EXPECTED_COUNT} municipalities, got {len(rows)}")
    ids = [r["municipality_id"] for r in rows]
    if len(set(ids)) != len(ids):
        problems.append("duplicate municipality_id values present")
    fips = [r["county_fips"] for r in rows if r["county_fips"]]
    if len(set(fips)) != len(fips):
        problems.append("duplicate county_fips values present")
    return problems


def ingest(root: Path | None = None) -> dict[str, Any]:
    root = root or REPO_ROOT
    muni_rows, evidence_rows = build_rows(root)
    problems = check_coverage(muni_rows)
    if problems:
        raise ValueError("municipality coverage check failed: " + "; ".join(problems))

    write_municipalities(muni_rows, root / MUNI_OUT)
    evidence_manifest = merge_evidence(root / EVIDENCE_OUT, evidence_rows)

    manifest = {
        "producer_script": "scripts/ingest_municipalities.py",
        "producer_phase": "CANONICAL_V1_MUNICIPALITIES_INGEST",
        "source_inputs": [REFERENCE],
        "output": MUNI_OUT,
        "row_count": len(muni_rows),
        "expected_count": EXPECTED_COUNT,
        "coverage_pct": round(100.0 * len(muni_rows) / EXPECTED_COUNT, 2),
        "evidence_rows_added": len(evidence_rows),
        "evidence_table_rows": evidence_manifest["row_count"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    manifest_path = root / MANIFEST_OUT
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ingest PR municipalities into canonical_v1.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--check", action="store_true", help="Validate coverage without writing.")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()

    if args.check:
        rows, _ = build_rows(root)
        problems = check_coverage(rows)
        print(
            json.dumps({"ok": not problems, "row_count": len(rows), "problems": problems}, indent=2)
        )
        return 0 if not problems else 1

    manifest = ingest(root)
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
