"""
Merge offline SAM bulk-resolved UEIs into the PR contracts master.

Combines:
  data/staging/processed/enrichment/sam_bulk_v2_matches.csv       (k1 exact, authoritative)
  data/staging/processed/enrichment/sam_bulk_v2_confirmed_k2.csv  (k2 confirmed >= 0.85)

Patches data/staging/processed/pr_contracts_master.csv by vendor_name
(exact, then normalized fallback) and writes master_enriched.csv,
backing up any existing copy first. Staging-only; production paths untouched.

Usage: python3 scripts/merge_sam_bulk_master.py
"""

from __future__ import annotations

import csv
import shutil
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

ENR = PROJECT_ROOT / "data" / "staging" / "processed" / "enrichment"
MASTER = PROJECT_ROOT / "data" / "staging" / "processed" / "pr_contracts_master.csv"
SOURCES = ["sam_bulk_v2_matches.csv", "sam_bulk_v2_confirmed_k2.csv"]
NEW_COLS = ["recipient_uei", "recipient_cage", "sam_legal_name", "sam_state", "uei_source"]


def _normalize_vendor(name: str) -> str:
    """Import lazily so this script remains runnable as a direct file."""
    from scripts.sam_enrichment import normalize_vendor

    return normalize_vendor(name)


def load_resolved() -> dict:
    by_name: dict[str, dict] = {}
    for fn in SOURCES:
        p = ENR / fn
        if not p.exists():
            print(f"  warn: {fn} missing, skipping")
            continue
        with open(p, encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if not r.get("uei"):
                    continue
                rec = {
                    "uei": r["uei"],
                    "cage": r.get("cage", ""),
                    "sam_name": r.get("sam_name", ""),
                    "state": r.get("state", ""),
                    "src": r.get("source", "SAM_BULK_V2") + ("/k2" if "k2" in fn else ""),
                }
                by_name.setdefault(r["vendor_name"], rec)
                by_name.setdefault(_normalize_vendor(r["vendor_name"]), rec)
    return by_name


def main() -> None:
    if not MASTER.exists():
        sys.exit(f"master not found: {MASTER}")
    resolved = load_resolved()

    with open(MASTER, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fields = list(reader.fieldnames or [])
        rows = list(reader)
    for c in NEW_COLS:
        if c not in fields:
            fields.append(c)

    patched = 0
    vendors_hit: set[str] = set()
    val_total = val_patched = 0.0
    for row in rows:
        try:
            amt = float(row.get("obligated_amount", 0) or 0)
        except (ValueError, TypeError):
            amt = 0.0
        val_total += amt
        vn = (row.get("vendor_name") or "").strip()
        m = resolved.get(vn) or resolved.get(_normalize_vendor(vn))
        if m and not row.get("recipient_uei"):
            row["recipient_uei"] = m["uei"]
            row["recipient_cage"] = m["cage"]
            row["sam_legal_name"] = m["sam_name"]
            row["sam_state"] = m["state"]
            row["uei_source"] = m["src"]
            patched += 1
            vendors_hit.add(vn)
            val_patched += amt

    out = ENR / "master_enriched.csv"
    if out.exists():
        bak = out.with_suffix(f".csv.bak.{datetime.now():%Y%m%d%H%M%S}")
        shutil.copy2(out, bak)
        print(f"  backed up existing -> {bak.name}")
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    print(f"master rows:        {len(rows):,}")
    print(f"rows patched w/UEI: {patched:,}  ({patched / max(len(rows), 1) * 100:.1f}%)")
    print(f"distinct vendors:   {len(vendors_hit):,}")
    print(
        f"obligated value:    ${val_patched:,.0f} / ${val_total:,.0f}"
        f"  ({val_patched / max(val_total, 1) * 100:.1f}%)"
    )
    print(f"output:             {out}")


if __name__ == "__main__":
    main()
