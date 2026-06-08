"""Ingest PR municipal bonds into Canonical v1 ``debt_instruments.csv`` (WS-J).

Source surface: ``KNOWN_EMMA_BONDS`` — the deterministic, committed-in-code set
of real Puerto Rico municipal bonds (with CUSIPs) in ``scripts/download_emma.py``.
No network is used; this reuses the existing in-repo EMMA seed rather than the
gitignored downloaded CSV. Evidence-first: one accepted Tier-T2 evidence row per
instrument (EMMA registry filing), referenced by ``evidence_id``.

``debt_class`` is mapped from the issuer to the schema enum
(GO / COFINA / PREPA / PRASA / HTA / other). Issuer entity resolution for
HOLDS_DEBT edges happens later in ``build_edges.py``.

Roadmap: WS-J, tasks T135-T146. Stdlib only.

CLI::

    python scripts/ingest_debt.py            # write debt_instruments + evidence
    python scripts/ingest_debt.py --check     # summarize without writing
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

from contract_sweeper.runtime.canonical_ids import debt_id
from scripts.build_edges import build_resolver, resolve
from scripts.build_evidence import Evidence, make_evidence, merge_evidence
from scripts.download_emma import KNOWN_EMMA_BONDS

REPO_ROOT = Path(__file__).resolve().parents[1]
DEBT_OUT = "data/canonical_v1/debt_instruments.csv"
EVIDENCE_OUT = "data/canonical_v1/evidence.csv"
MANIFEST_OUT = "data/manifests/canonical_v1/debt_instruments.json"
SOURCE_NAME = "EMMA PR Municipal Bonds (known seed)"

VALID_CLASSES = {"GO", "COFINA", "PREPA", "PRASA", "HTA", "other"}

DEBT_COLUMNS = [
    "debt_id",
    "issuer_entity_id",
    "debt_class",
    "series",
    "issue_year",
    "par_amount",
    "currency",
    "maturity_date",
    "status",
    "confidence",
    "evidence_id",
    "review_status",
    "notes",
]


def classify(issuer_normalized: str, description: str) -> str:
    """Map an issuer/description to the debt_class enum."""
    iu = (issuer_normalized or "").upper()
    desc = (description or "").upper()
    if "SALES TAX FINANCING" in iu or "COFINA" in desc:
        return "COFINA"
    if "ELECTRIC POWER" in iu or "PREPA" in desc:
        return "PREPA"
    if "AQUEDUCT AND SEWER" in iu or "PRASA" in desc:
        return "PRASA"
    if "HIGHWAYS AND TRANSPORTATION" in iu or desc.startswith("HTA"):
        return "HTA"
    if iu == "COMMONWEALTH OF PUERTO RICO" or desc.startswith("GO BONDS"):
        return "GO"
    return "other"


def _series_and_year(bond: dict[str, str]) -> tuple[str, str]:
    """Extract a series label (from description) and the issue year."""
    desc = (bond.get("description") or "").strip()
    series = desc.split("Series")[-1].strip() if "Series" in desc else desc
    issue_date = (bond.get("issue_date") or "").strip()
    year = issue_date[:4] if len(issue_date) >= 4 and issue_date[:4].isdigit() else ""
    return series, year


def build_rows(root: Path | None = None) -> dict[str, Any]:
    """Build debt rows (issuer resolved to a canonical entity) + evidence + skips.

    Only bonds whose issuer resolves to an existing ``entities.csv`` node are
    written — ``issuer_entity_id`` is required by the schema. Bonds with a
    non-canonical issuer are reported as skipped (candidates for a future entity
    seed), never written with a dangling reference.
    """
    root = root or REPO_ROOT
    resolver = build_resolver(root)
    debt_rows: list[dict[str, Any]] = []
    evidence_rows: list[Evidence] = []
    skipped: list[dict[str, str]] = []
    seen: set[str] = set()
    for bond in KNOWN_EMMA_BONDS:
        issuer = (bond.get("issuer_name") or "").strip()
        issuer_norm = (bond.get("issuer_normalized") or "").strip()
        cusip = (bond.get("cusip") or "").strip()
        issuer_eid = resolve(resolver, "Entity", issuer) or resolve(resolver, "Entity", issuer_norm)
        if issuer_eid is None:
            skipped.append({"cusip": cusip, "reason": f"unresolved issuer {issuer!r}"})
            continue
        debt_class = classify(issuer_norm, bond.get("description", ""))
        series, year = _series_and_year(bond)
        did = debt_id(issuer_norm or issuer, debt_class, f"{year}_{cusip}")
        if did in seen:
            continue
        seen.add(did)
        ev = make_evidence(
            source_type="filing",
            source_name=SOURCE_NAME,
            source_path_or_url="https://emma.msrb.org/",
            page_or_line_ref=f"CUSIP {cusip}",
            claim=(
                f"{issuer} issued '{bond.get('description', '').strip()}' "
                f"(CUSIP {cusip}; par {bond.get('par_amount', '')}; "
                f"maturity {bond.get('maturity_date', '')})."
            ),
            extraction_method="manual",
            evidence_tier="T2",
            review_status="accepted",
        )
        evidence_rows.append(ev)
        debt_rows.append(
            {
                "debt_id": did,
                "issuer_entity_id": issuer_eid,
                "debt_class": debt_class,
                "series": series,
                "issue_year": year,
                "par_amount": (bond.get("par_amount") or "").strip(),
                "currency": "USD",
                "maturity_date": (bond.get("maturity_date") or "").strip(),
                "status": "",
                "confidence": ev.confidence,
                "evidence_id": ev.evidence_id,
                "review_status": "accepted",
                "notes": f"cusip={cusip}; issuer={issuer}",
            }
        )
    return {"debt_rows": debt_rows, "evidence_rows": evidence_rows, "skipped": skipped}


def check(rows: list[dict[str, Any]]) -> list[str]:
    problems: list[str] = []
    if not rows:
        problems.append("no debt rows produced")
    ids = [r["debt_id"] for r in rows]
    if len(set(ids)) != len(ids):
        problems.append("duplicate debt_id values present")
    if any(r["debt_class"] not in VALID_CLASSES for r in rows):
        problems.append("invalid debt_class present")
    return problems


def _write(rows: list[dict[str, Any]], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=DEBT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def ingest(root: Path | None = None) -> dict[str, Any]:
    root = root or REPO_ROOT
    built = build_rows(root)
    rows, evidence_rows = built["debt_rows"], built["evidence_rows"]
    problems = check(rows)
    if problems:
        raise ValueError("debt ingest check failed: " + "; ".join(problems))
    _write(rows, root / DEBT_OUT)
    evidence_manifest = merge_evidence(root / EVIDENCE_OUT, evidence_rows)
    class_counts: dict[str, int] = {}
    for r in rows:
        class_counts[r["debt_class"]] = class_counts.get(r["debt_class"], 0) + 1
    manifest = {
        "producer_script": "scripts/ingest_debt.py",
        "producer_phase": "CANONICAL_V1_DEBT_INGEST",
        "source_inputs": ["scripts/download_emma.py:KNOWN_EMMA_BONDS"],
        "row_count": len(rows),
        "debt_class_counts": class_counts,
        "skipped_non_canonical_issuers": len(built["skipped"]),
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
    parser = argparse.ArgumentParser(
        description="Ingest PR municipal bonds into canonical_v1 debt."
    )
    parser.add_argument("--root", default=".")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    if args.check:
        built = build_rows(root)
        rows = built["debt_rows"]
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
