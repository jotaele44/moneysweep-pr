"""Build a name-alias cluster registry from all staged CSVs.

Scans data/staging/processed/**/*.csv, clusters entity names by their
normalized form, and writes:
  data/staging/processed/enrichment/alias_registry.json

Each entry is a candidate alias cluster — not a verified legal identity.

Usage:
  python3 scripts/alias_registry_builder.py
  python3 scripts/alias_registry_builder.py --root /path/to/repo
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from contract_sweeper.runtime.name_normalization import normalize_name

NAME_FIELDS = [
    "recipient_name", "vendor_name", "award_recipient_name",
    "prime_recipient_name", "sub_recipient_name", "client_name",
    "registrant_name", "contractor", "applicant",
]
AMOUNT_FIELDS = [
    "obligated_amount", "total_obligation", "obligation_amount",
    "amount", "subaward_amount",
]


def _amt(row: dict) -> float:
    for f in AMOUNT_FIELDS:
        v = row.get(f)
        if v not in (None, ""):
            try:
                return float(str(v).replace(",", "").replace("$", ""))
            except Exception:
                pass
    return 0.0


def _iter_rows(path: Path):
    if not path.exists() or path.suffix.lower() != ".csv":
        return
    try:
        with path.open(encoding="utf-8-sig", newline="") as f:
            yield from csv.DictReader(f)
    except Exception:
        return


def build_alias_registry(root: Path) -> dict:
    processed = root / "data" / "staging" / "processed"
    clusters: dict = defaultdict(lambda: {
        "aliases": set(), "sources": set(), "row_count": 0, "total_amount": 0.0,
    })
    for path in (processed.rglob("*.csv") if processed.exists() else []):
        for row in _iter_rows(path):
            for field in NAME_FIELDS:
                raw = (row.get(field) or "").strip()
                norm = normalize_name(raw)
                if len(norm) < 3:
                    continue
                c = clusters[norm]
                c["aliases"].add(raw)
                c["sources"].add(path.name)
                c["row_count"] += 1
                c["total_amount"] += _amt(row)

    entries = [
        {
            "normalized_name": n,
            "canonical_name": sorted(c["aliases"], key=lambda x: (-len(x), x))[0],
            "aliases": sorted(c["aliases"]),
            "sources": sorted(c["sources"]),
            "row_count": c["row_count"],
            "total_amount": round(c["total_amount"], 2),
            "parent_uei": "",
            "parent_name": "",
            "status": "candidate_alias_cluster",
            "manual_review_required": len(c["aliases"]) > 1,
        }
        for n, c in sorted(clusters.items(), key=lambda kv: (-kv[1]["total_amount"], kv[0]))
    ]

    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "entry_count": len(entries),
        "identity_warning": (
            "Alias clusters are normalized-name candidates, "
            "not verified legal identity."
        ),
        "entries": entries,
    }
    enrichment_dir = processed / "enrichment"
    enrichment_dir.mkdir(parents=True, exist_ok=True)
    (enrichment_dir / "alias_registry.json").write_text(
        json.dumps(out, indent=2), encoding="utf-8"
    )
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    a = p.parse_args(argv)
    result = build_alias_registry(Path(a.root))
    print(json.dumps({"entry_count": result["entry_count"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
