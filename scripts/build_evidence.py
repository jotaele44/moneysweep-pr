"""Build the Canonical Entity Relationship Model v1 ``evidence.csv`` table.

Evidence-first: this producer runs *before* any node/edge builder so that every
downstream row can reference a stable ``evidence_id``. It turns raw source
surfaces (CSV/registry exports, web/filing references, OCR'd PDFs, court
dockets) into evidence rows with deterministic IDs, derived tiers, and
tier-aware confidence, deduplicates them, and writes the table plus a manifest.

Stdlib only. Real source acquisition (network, PDF binaries) is out of scope
here; loaders accept already-extracted *claim records* — dicts describing one
sourced claim — keeping the logic testable without external data.

CLI::

    python scripts/build_evidence.py --claims claims.json --out data/canonical_v1/evidence.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from moneysweep.runtime.canonical_ids import evidence_id
from moneysweep.runtime.evidence_tiers import (
    claim_tier_for,
    derive_tier,
    score_evidence,
)

EVIDENCE_COLUMNS = [
    "evidence_id",
    "source_type",
    "source_name",
    "source_path_or_url",
    "page_or_line_ref",
    "claim",
    "evidence_tier",
    "extraction_method",
    "confidence",
    "review_status",
]


@dataclass
class Evidence:
    """One source-backed claim row."""

    evidence_id: str
    source_type: str
    source_name: str
    source_path_or_url: str
    page_or_line_ref: str
    claim: str
    evidence_tier: str
    extraction_method: str
    confidence: float
    review_status: str = "pending"

    def claim_tier(self) -> str:
        """CLAIM_LANGUAGE_POLICY claim tier implied by this evidence."""
        return claim_tier_for(self.evidence_tier, self.review_status)

    def as_row(self) -> dict[str, Any]:
        return asdict(self)


def make_evidence(
    *,
    source_type: str,
    source_name: str,
    claim: str,
    source_path_or_url: str = "",
    page_or_line_ref: str = "",
    extraction_method: str = "parser",
    evidence_tier: str | None = None,
    ocr_confidence: float | None = None,
    review_status: str = "pending",
) -> Evidence:
    """Construct an Evidence row, deriving tier/confidence/ID deterministically."""
    tier = evidence_tier or derive_tier(source_type, extraction_method)
    conf = score_evidence(tier, extraction_method, ocr_confidence)
    eid = evidence_id(source_name, page_or_line_ref, claim)
    return Evidence(
        evidence_id=eid,
        source_type=source_type,
        source_name=source_name,
        source_path_or_url=source_path_or_url,
        page_or_line_ref=page_or_line_ref,
        claim=claim,
        evidence_tier=tier,
        extraction_method=extraction_method,
        confidence=conf,
        review_status=review_status,
    )


def from_claim_records(records: Iterable[dict[str, Any]]) -> list[Evidence]:
    """Build evidence rows from generic claim-record dicts (any source surface)."""
    out: list[Evidence] = []
    for rec in records:
        out.append(
            make_evidence(
                source_type=rec.get("source_type", "other"),
                source_name=rec.get("source_name", ""),
                claim=rec.get("claim", ""),
                source_path_or_url=rec.get("source_path_or_url", ""),
                page_or_line_ref=str(rec.get("page_or_line_ref", "")),
                extraction_method=rec.get("extraction_method", "parser"),
                evidence_tier=rec.get("evidence_tier"),
                ocr_confidence=rec.get("ocr_confidence"),
                review_status=rec.get("review_status", "pending"),
            )
        )
    return out


def from_csv_source(
    path: Path,
    *,
    source_name: str | None = None,
    claim_template: str = "row {line}: {row}",
    source_type: str = "csv",
    extraction_method: str = "parser",
) -> list[Evidence]:
    """Emit one evidence row per data row of a CSV source, referencing the line."""
    source_name = source_name or path.name
    rows: list[Evidence] = []
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for i, row in enumerate(reader, start=2):  # line 1 is the header
            claim = claim_template.format(line=i, row=json.dumps(row, ensure_ascii=False))
            rows.append(
                make_evidence(
                    source_type=source_type,
                    source_name=source_name,
                    source_path_or_url=str(path),
                    page_or_line_ref=f"row {i}",
                    claim=claim,
                    extraction_method=extraction_method,
                )
            )
    return rows


def read_evidence(path: Path) -> list[Evidence]:
    """Load an existing evidence.csv into Evidence objects (for merge/append).

    Returns an empty list if the file is missing or header-only.
    """
    if not path.exists():
        return []
    out: list[Evidence] = []
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            if not (row.get("evidence_id") or "").strip():
                continue
            out.append(
                Evidence(
                    evidence_id=row.get("evidence_id", ""),
                    source_type=row.get("source_type", ""),
                    source_name=row.get("source_name", ""),
                    source_path_or_url=row.get("source_path_or_url", ""),
                    page_or_line_ref=row.get("page_or_line_ref", ""),
                    claim=row.get("claim", ""),
                    evidence_tier=row.get("evidence_tier", ""),
                    extraction_method=row.get("extraction_method", ""),
                    confidence=float(row["confidence"])
                    if (row.get("confidence") or "").strip()
                    else 0.0,
                    review_status=row.get("review_status", "pending"),
                )
            )
    return out


def merge_evidence(path: Path, new_items: Iterable[Evidence]) -> dict[str, Any]:
    """Append new evidence to an existing table, dedupe by id, and rewrite it."""
    combined = dedupe_evidence(list(read_evidence(path)) + list(new_items))
    return write_evidence(combined, path)


def dedupe_evidence(items: Iterable[Evidence]) -> list[Evidence]:
    """Collapse evidence with the same (source_name, page_or_line_ref, claim).

    Identical inputs produce identical ``evidence_id`` (see ``canonical_ids``),
    so dedup is keyed on that id; the highest-confidence row wins.
    """
    best: dict[str, Evidence] = {}
    for ev in items:
        cur = best.get(ev.evidence_id)
        if cur is None or ev.confidence > cur.confidence:
            best[ev.evidence_id] = ev
    return list(best.values())


def write_evidence(items: list[Evidence], out_path: Path) -> dict[str, Any]:
    """Write evidence rows to CSV and return a manifest dict."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=EVIDENCE_COLUMNS)
        writer.writeheader()
        for ev in items:
            writer.writerow(ev.as_row())
    return build_manifest(items, out_path)


def build_manifest(items: list[Evidence], out_path: Path) -> dict[str, Any]:
    tier_counts: dict[str, int] = {}
    status_counts: dict[str, int] = {}
    for ev in items:
        tier_counts[ev.evidence_tier] = tier_counts.get(ev.evidence_tier, 0) + 1
        status_counts[ev.review_status] = status_counts.get(ev.review_status, 0) + 1
    return {
        "producer_script": "scripts/build_evidence.py",
        "producer_phase": "CANONICAL_V1_EVIDENCE_BUILD",
        "output": str(out_path),
        "row_count": len(items),
        "tier_counts": tier_counts,
        "review_status_counts": status_counts,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build canonical_v1 evidence.csv.")
    parser.add_argument("--claims", help="JSON file: array of claim-record dicts.")
    parser.add_argument("--csv-source", help="CSV source file: one evidence row per data row.")
    parser.add_argument("--out", default="data/canonical_v1/evidence.csv")
    parser.add_argument("--manifest", help="Optional path to write the JSON manifest.")
    args = parser.parse_args(argv)

    items: list[Evidence] = []
    if args.claims:
        records = json.loads(Path(args.claims).read_text(encoding="utf-8"))
        items.extend(from_claim_records(records))
    if args.csv_source:
        items.extend(from_csv_source(Path(args.csv_source)))

    items = dedupe_evidence(items)
    manifest = write_evidence(items, Path(args.out))
    if args.manifest:
        Path(args.manifest).write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
