"""
SAM.gov Entity Management Public Extract V2 — offline bulk UEI resolver.

Streams the monthly SAM_PUBLIC_MONTHLY_V2_*.dat extract (pipe-delimited,
one entity per line, '!end' trailer) and resolves PR-contract vendor names
to UEI / CAGE / status / state by exact normalized-name match — no API,
no rate limit. Designed to do the bulk of entity resolution so the
rate-limited SAM API (scripts/sam_enrichment.py) only handles the residual.

Field layout (0-indexed, V2):
  [0] UEI  [3] CAGE  [5] SAM extract code (A=active)  [11] legal name
  [12] DBA name  [18] physical-address state

Match keys (symmetric, applied to both targets and SAM names):
  k1  = upper, non-alnum -> space, collapse           (precise legal-name match)
  k2  = k1 with trailing legal suffixes stripped      (INC/LLC/CORP... fallback)

Usage:
  python3 scripts/ingest_sam_bulk.py --dat /path/to/SAM_PUBLIC_MONTHLY_V2_YYYYMMDD.dat
  python3 scripts/ingest_sam_bulk.py            # auto-detect newest .dat in known dirs
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))  # so `from scripts.*` resolves when run as a file

DAT_SEARCH_DIRS = [
    Path(os.environ["SAM_BULK_DIR"]) if os.environ.get("SAM_BULK_DIR") else None,
    PROJECT_ROOT / "data" / "raw" / "sam",
]
DAT_SEARCH_DIRS = [p for p in DAT_SEARCH_DIRS if p is not None]

# Genuine legal-form suffixes ONLY. Descriptive words (CONSTRUCTION, SERVICES,
# GROUP, SOLUTIONS, ...) are deliberately excluded: stripping them over-merges
# distinct firms (e.g. "RIO CONSTRUCTION" -> "RIO"), producing false matches.
_SUFFIX = re.compile(
    r"\b(INC|INCORPORATED|CORP|CORPORATION|CO|COMPANY|LLC|LLP|LP|LTD|LIMITED|"
    r"PSC|SE|SP|PA|PC)\b"
)
_NONALNUM = re.compile(r"[^A-Z0-9 ]")
_WS = re.compile(r"\s+")


def k1(name: str) -> str:
    return _WS.sub(" ", _NONALNUM.sub(" ", name.upper())).strip()


def k2(key1: str) -> str:
    return _WS.sub(" ", _SUFFIX.sub(" ", key1)).strip()


def find_dat(explicit: str | None) -> Path:
    if explicit:
        p = Path(explicit)
        if not p.exists():
            sys.exit(f"--dat not found: {p}")
        return p
    cands: list[Path] = []
    for d in DAT_SEARCH_DIRS:
        if d.exists():
            cands += sorted(d.glob("SAM_PUBLIC_MONTHLY_V2_*.dat"))
    if not cands:
        sys.exit("No SAM_PUBLIC_MONTHLY_V2_*.dat found. Pass --dat explicitly.")
    return cands[-1]  # newest by name (date-suffixed)


def load_targets(root: Path) -> dict:
    path = root / "data" / "staging" / "processed" / "vendor_targets.csv"
    if not path.exists():
        sys.exit(f"vendor_targets.csv not found at {path}")
    by_k1: dict[str, dict] = {}
    by_k2: dict[str, dict] = {}
    with open(path, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            vn = (r.get("vendor_name") or "").strip()
            if not vn:
                continue
            tgt = {
                "vendor_name": vn,
                "total_value": float(r.get("total_value", 0) or 0),
            }
            a = k1(vn)
            by_k1.setdefault(a, tgt)
            by_k2.setdefault(k2(a), tgt)
    return {"by_k1": by_k1, "by_k2": by_k2}


def run(dat: Path, root: Path, limit: int | None = None) -> dict:
    t = load_targets(root)
    by_k1, by_k2 = t["by_k1"], t["by_k2"]
    n_targets = len(by_k1)
    matches: dict[str, dict] = {}  # vendor_name -> resolved row

    t0 = time.time()
    scanned = 0
    with open(dat, encoding="latin-1") as fh:
        header = fh.readline()
        for line in fh:
            if line.startswith("EOF"):
                break
            scanned += 1
            if limit and scanned > limit:
                break
            p = line.split("|", 19)
            if len(p) < 19:
                continue
            uei, cage, status, legal, dba, state = (
                p[0], p[3], p[5], p[11], p[12], p[18],
            )
            if not uei:
                continue
            for nm in (legal, dba):
                if not nm:
                    continue
                a = k1(nm)
                tgt = by_k1.get(a)
                tier = "k1_exact"
                if not tgt:
                    tgt = by_k2.get(k2(a))
                    tier = "k2_suffix"
                if not tgt:
                    continue
                vn = tgt["vendor_name"]
                prev = matches.get(vn)
                # prefer active status; prefer legal over dba; prefer k1 over k2
                cand_rank = (status == "A", nm is legal, tier == "k1_exact")
                if prev and prev["_rank"] >= cand_rank:
                    continue
                matches[vn] = {
                    "vendor_name": vn,
                    "total_value": tgt["total_value"],
                    "uei": uei,
                    "cage": cage,
                    "sam_name": legal,
                    "status": "Active" if status == "A" else status,
                    "state": state,
                    "match_tier": tier,
                    "matched_on": "legal" if nm is legal else "dba",
                    "source": "SAM_BULK_V2",
                    "_rank": cand_rank,
                }
                break

    elapsed = time.time() - t0
    resolved_val = sum(m["total_value"] for m in matches.values())
    total_val = sum(x["total_value"] for x in by_k1.values())
    return {
        "dat": dat.name,
        "header": header.strip(),
        "entities_scanned": scanned,
        "targets": n_targets,
        "matched": len(matches),
        "coverage_pct": round(len(matches) / max(n_targets, 1) * 100, 2),
        "value_matched": round(resolved_val, 2),
        "value_total": round(total_val, 2),
        "value_coverage_pct": round(resolved_val / max(total_val, 1) * 100, 2),
        "elapsed_s": round(elapsed, 1),
        "_matches": matches,
    }


def confirm_k2(r_rows: list[dict]) -> tuple[list[dict], list[dict]]:
    """Score k2 suffix candidates with the project's own matcher (same logic
    and 0.85 threshold the SAM API leg uses). Returns (confirmed, rejected)."""
    try:
        from scripts.sam_enrichment import (
            MATCH_THRESHOLD, name_similarity, normalize_vendor,
        )
    except Exception:
        return [], r_rows  # scorer unavailable -> treat all as unconfirmed
    confirmed, rejected = [], []
    for r in r_rows:
        s = name_similarity(normalize_vendor(r["vendor_name"]),
                            normalize_vendor(r["sam_name"]))
        r = {**r, "match_score": round(s, 3)}
        (confirmed if s >= MATCH_THRESHOLD else rejected).append(r)
    return confirmed, rejected


def write_outputs(summary: dict, root: Path) -> dict:
    out_dir = root / "data" / "staging" / "processed" / "enrichment"
    out_dir.mkdir(parents=True, exist_ok=True)
    cols = ["vendor_name", "total_value", "uei", "cage", "sam_name",
            "status", "state", "match_tier", "matched_on", "source"]
    auth = out_dir / "sam_bulk_v2_matches.csv"          # k1_exact — authoritative
    review = out_dir / "sam_bulk_v2_review.csv"         # k2_suffix — all candidates
    confirmed_p = out_dir / "sam_bulk_v2_confirmed_k2.csv"  # k2 passing >=0.85
    a_rows = [m for m in summary["_matches"].values() if m["match_tier"] == "k1_exact"]
    r_rows = [m for m in summary["_matches"].values() if m["match_tier"] == "k2_suffix"]
    confirmed, rejected = confirm_k2(r_rows)

    def _dump(path, data, extra_cols=()):
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(cols) + list(extra_cols),
                               extrasaction="ignore")
            w.writeheader()
            for m in sorted(data, key=lambda x: x["total_value"], reverse=True):
                w.writerow(m)

    _dump(auth, a_rows)
    _dump(review, r_rows, ("match_score",))
    _dump(confirmed_p, confirmed, ("match_score",))
    return {"auth": auth, "review": review, "confirmed": confirmed_p,
            "n_auth": len(a_rows), "n_review": len(r_rows),
            "n_confirmed": len(confirmed), "n_rejected": len(rejected),
            "v_auth": sum(m["total_value"] for m in a_rows)}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dat", help="Path to SAM_PUBLIC_MONTHLY_V2_*.dat")
    ap.add_argument("--limit", type=int, help="Cap entities scanned (debug)")
    ap.add_argument("--root", default=str(PROJECT_ROOT))
    args = ap.parse_args()
    root = Path(args.root)
    dat = find_dat(args.dat)
    s = run(dat, root, limit=args.limit)
    o = write_outputs(s, root)
    tv = s["value_total"]
    print(f"DAT:              {s['dat']}  ({s['header']})")
    print(f"Entities:         {s['entities_scanned']:,}")
    print(f"Targets:          {s['targets']:,}")
    print(f"Authoritative:    {o['n_auth']:,}  ({o['n_auth']/max(s['targets'],1)*100:.1f}% count)"
          f"  ${o['v_auth']:,.0f}  ({o['v_auth']/max(tv,1)*100:.1f}% value)")
    print(f"Confirmed (k2):   {o['n_confirmed']:,}  (>=0.85) -> {o['confirmed'].name}")
    print(f"Rejected (k2):    {o['n_rejected']:,}  -> residual")
    print(f"Residual for API: {s['targets']-o['n_auth']-o['n_confirmed']:,}")
    print(f"Elapsed:          {s['elapsed_s']}s")
    print(f"Output:           {o['auth']}")
