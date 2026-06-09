#!/usr/bin/env python3
"""Post-match QA for PREPA full-universe continuity outputs.

Takes a continuity actor registry or entity master and emits:
- validated canonical registry
- human review queue
- suppressed false-positive candidates

This is a QA gate. It does not create allegations.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

ADDRESS_TERMS = {
    "ATTN",
    "ATTENTION",
    "ADDRESS",
    "FILE",
    "ST",
    "STREET",
    "AVE",
    "AVENUE",
    "ROAD",
    "RD",
    "CARR",
    "CARRETERA",
    "SUITE",
    "STE",
    "OFICINA",
    "OFFICE",
    "PLAZA",
    "BLDG",
    "BUILDING",
    "CHICAGO",
    "RALEIGH",
    "IL",
    "NC",
    "PR",
    "ZIP",
    "PO",
    "BOX",
    "C",
    "O",
    "RE",
    "RES",
    "TO",
    "PAYSHPERE",
    "PAYSPHERE",
    "CIRCLE",
    "CENTRO",
    "INTERNACIONAL",
    "MUNDO",
    "BORI",
    "URB",
    "ALTURAS",
    "PENUELAS",
    "SCOTIABANK",
    "ROOSEVELT",
    "ELEONOR",
}

GENERIC_TERMS = {
    "GENERAL",
    "SERVICES",
    "SERVICE",
    "CONTRACTOR",
    "CONTRACTORS",
    "CONSTRUCTION",
    "SUPPLIES",
    "PUERTO",
    "RICO",
    "CARIBE",
    "INC",
    "LLC",
    "LP",
    "LLP",
    "PSC",
    "CORP",
    "COMPANY",
    "CO",
    "BLACK",
    "CAL",
    "CHECK",
    "MOTRIZ",
    "MACHINERY",
}

PUBLIC_AUTHORITY_TERMS = {
    "PUERTO RICO ELECTRIC POWER AUTHORITY",
    "AUTORIDAD DE ENERGIA ELECTRICA",
    "FISCAL AGENCY AND FINANCIAL ADVISORY AUTHORITY",
    "SECRETARIO DE HACIENDA",
    "ADMINISTRACION DE SERVICIOS GENERALES",
}

CANONICAL_PATTERNS = [
    ("AIREKO", "AIREKO"),
    ("AECOM", "AECOM"),
    ("BLACK VEATCH", "BLACK & VEATCH"),
    ("BLACK AND VEATCH", "BLACK & VEATCH"),
    ("PUMA ENERGY", "PUMA ENERGY CARIBE"),
    ("ECOELECTRICA", "ECOELECTRICA"),
    ("FREEPOINT", "FREEPOINT COMMODITIES"),
    ("VITOL", "VITOL"),
    ("PROSKAUER", "PROSKAUER ROSE"),
    ("PAUL HASTINGS", "PAUL HASTINGS"),
    ("ALSTOM", "ALSTOM"),
    ("TEC GENERAL", "TEC GENERAL CONTRACTORS"),
    ("ERNST YOUNG", "ERNST & YOUNG"),
    ("PREPA", "PUERTO RICO ELECTRIC POWER AUTHORITY"),
    ("PUERTO RICO ELECTRIC POWER AUTHORITY", "PUERTO RICO ELECTRIC POWER AUTHORITY"),
    ("FISCAL AGENCY AND FINANCIAL ADVISORY AUTHORITY", "AAFAF"),
]


def norm(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9 &]+", " ", str(value).upper())
    return re.sub(r"\s+", " ", value).strip()


def strip_metadata(name: str) -> str:
    toks = norm(name).split()
    kept = []
    for tok in toks:
        if tok in ADDRESS_TERMS or tok.isdigit():
            break
        kept.append(tok)
    if not kept:
        kept = [t for t in toks[:5] if not t.isdigit()]
    return " ".join(kept).strip()


def canonical_name(name: str) -> str:
    cleaned = strip_metadata(name)
    compact = cleaned.replace("&", "AND")
    for pattern, canon in CANONICAL_PATTERNS:
        if pattern in compact:
            return canon
    return cleaned


def generic_ratio(name: str) -> float:
    toks = norm(name).split()
    if not toks:
        return 1.0
    return sum(1 for t in toks if t in GENERIC_TERMS or t in ADDRESS_TERMS) / len(toks)


def classify_status(row: dict[str, str], canon: str, cleaned: str) -> tuple[str, str]:
    raw = norm(row.get("normalized_name") or row.get("entity_name") or "")
    try:
        temporal_edges = int(float(row.get("temporal_edges", row.get("match_count", 0)) or 0))
    except ValueError:
        temporal_edges = 0
    try:
        dataset_count = int(float(row.get("dataset_count", 0) or 0))
    except ValueError:
        dataset_count = 0
    gr = generic_ratio(raw)

    if any(term in raw for term in PUBLIC_AUTHORITY_TERMS):
        return "review", "public_authority_or_self_node"
    if gr >= 0.55 and dataset_count <= 1:
        return "suppress", "generic_token_low_dataset_support"
    if len(cleaned.split()) <= 1:
        return "suppress", "insufficient_entity_name"
    if "ADDRESS ON FILE" in raw:
        return "review", "person_or_address_on_file"
    if dataset_count >= 2 or temporal_edges >= 20:
        if gr >= 0.55 or any(ch.isdigit() for ch in cleaned):
            return "review", "validated_signal_but_dirty_or_generic_canonical"
        return "validated", "multi_dataset_or_high_temporal_support"
    return "review", "needs_corrob_or_alias_resolution"


def read_csv(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, type=Path)
    ap.add_argument("--outdir", required=True, type=Path)
    args = ap.parse_args()

    rows = read_csv(args.input)
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)

    for row in rows:
        raw_name = row.get("normalized_name") or row.get("entity_name") or ""
        cleaned = strip_metadata(raw_name)
        canon = canonical_name(raw_name)
        row["cleaned_name"] = cleaned
        row["canonical_name"] = canon
        row["generic_ratio"] = round(generic_ratio(raw_name), 3)
        status, reason = classify_status(row, canon, cleaned)
        row["qa_status"] = status
        row["qa_reason"] = reason
        grouped[canon].append(row)

    canonical_rows = []
    review_rows = []
    suppressed_rows = []

    for canon, items in grouped.items():

        def num(row: dict[str, str], key: str) -> float:
            try:
                return float(row.get(key, 0) or 0)
            except ValueError:
                return 0.0

        best = max(
            items,
            key=lambda r: (
                num(r, "continuity_score"),
                num(r, "temporal_edges"),
                num(r, "match_count"),
            ),
        )
        total_edges = sum(num(r, "temporal_edges") for r in items)
        max_score = max(num(r, "continuity_score") for r in items)
        datasets = set()
        for r in items:
            ds = r.get("datasets", "")
            if ds.startswith("{"):
                try:
                    datasets.update(json.loads(ds).keys())
                except Exception:
                    pass
            else:
                datasets.update([x for x in ds.split(";") if x])
        merged: dict = dict(best)
        merged["alias_count"] = len(items)
        merged["merged_temporal_edges"] = int(total_edges)
        merged["merged_dataset_count"] = len(datasets)
        merged["merged_datasets"] = ";".join(sorted(datasets))
        merged["continuity_score"] = max_score

        statuses = {r["qa_status"] for r in items}
        if "validated" in statuses:
            canonical_rows.append(merged)
        elif "review" in statuses:
            review_rows.extend(items)
        else:
            suppressed_rows.extend(items)

    args.outdir.mkdir(parents=True, exist_ok=True)
    fields = (
        sorted(set().union(*(r.keys() for r in canonical_rows + review_rows + suppressed_rows)))
        if rows
        else []
    )
    write_csv(
        args.outdir / "prepa_top100_validated.csv",
        sorted(
            canonical_rows, key=lambda r: float(r.get("continuity_score", 0) or 0), reverse=True
        )[:100],
        fields,
    )
    write_csv(args.outdir / "prepa_review_queue.csv", review_rows, fields)
    write_csv(
        args.outdir / "prepa_suppressed_false_positive_candidates.csv", suppressed_rows, fields
    )

    summary = {
        "input_rows": len(rows),
        "validated_canonical_rows": len(canonical_rows),
        "review_rows": len(review_rows),
        "suppressed_rows": len(suppressed_rows),
        "outputs": {
            "validated": str(args.outdir / "prepa_top100_validated.csv"),
            "review": str(args.outdir / "prepa_review_queue.csv"),
            "suppressed": str(args.outdir / "prepa_suppressed_false_positive_candidates.csv"),
        },
    }
    (args.outdir / "prepa_postmatch_qa_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
