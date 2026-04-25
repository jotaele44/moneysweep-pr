"""
SAM.gov UEI Batch Enrichment — PR Contracts Master

Resolves vendor UEI/CAGE/DUNS from SAM.gov Entity Information API v2,
with USASpending.gov as a fallback for vendors not found in SAM.

Sources:
  Primary:  https://api.sam.gov/entity-information/v2/entities
  Fallback: https://api.usaspending.gov/api/v2/recipient/search/

API key: read from SAM_API_KEY env var or .env file (never committed to git).

Usage:
  python3 scripts/sam_enrichment.py               # full run
  python3 scripts/sam_enrichment.py --resume      # resume from checkpoint
  python3 scripts/sam_enrichment.py --dry-run     # validate config only
  python3 scripts/sam_enrichment.py --top 500     # first 500 vendors by value
"""

import argparse
import csv
import hashlib
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

import requests as _requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.config import (
    ENRICHMENT_OUTPUT_DIR,
    MASTER_PATH,
    PROJECT_ROOT,
    get_sam_api_key,
    setup_logging,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SAM_BASE_URL = "https://api.sam.gov/entity-information/v2/entities"
USAS_BASE_URL = "https://api.usaspending.gov/api/v2/recipient/search/"

BATCH_SIZE = 25
RATE_DELAY = 0.4
RETRY_MAX = 2        # was 3 — reduces timeout waste on failed lookups
RETRY_DELAY = 1.0    # was 2.0
MATCH_THRESHOLD = 0.85
COVERAGE_GATE = 0.60

STRIP_SUFFIXES = [
    r"\bINC\.?\b", r"\bCORP\.?\b", r"\bLLC\.?\b", r"\bLLP\.?\b",
    r"\bL\.P\.?\b", r"\bS\.E\.?\b", r"\bS\.P\.?\b", r"\bPSC\.?\b",
    r"\bLTD\.?\b", r"\bCO\.?\b", r"\bCOMPANY\b", r"\bCORPORATION\b",
    r"\bINCORPORATED\b", r"\bLIMITED\b", r"\bAUTHORITY\b",
    r"\bASSOCIATES\b", r"\bENTERPRISES\b", r"\bGROUP\b",
    r"\bSERVICES\b", r"\bSOLUTIONS\b", r"\bINTERNATIONAL\b",
    r"\bCONSTRUCTION\b", r"\bCONTRACTORS?\b", r"\bCONSULTANTS?\b",
]

# ---------------------------------------------------------------------------
# Normalization helpers
# ---------------------------------------------------------------------------

def normalize_vendor(name: str) -> str:
    """Canonical normalization: upper, strip punctuation, remove legal suffixes."""
    n = str(name).upper().strip()
    n = re.sub(r"[,.\-/&'()]", " ", n)
    for pat in STRIP_SUFFIXES:
        n = re.sub(pat, " ", n, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", n).strip()


def name_similarity(a: str, b: str) -> float:
    """Token-set Jaccard similarity between two normalized strings."""
    ta = set(a.split())
    tb = set(b.split())
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def vendor_hash(name: str) -> str:
    """Stable 12-char MD5 cache key for a vendor name."""
    return hashlib.md5(normalize_vendor(name).encode()).hexdigest()[:12]


# ---------------------------------------------------------------------------
# API calls
# ---------------------------------------------------------------------------

def sam_call(params: dict, api_key: str, timeout: tuple = (5, 7)):
    """GET SAM.gov entity-information API. Returns parsed JSON or None."""
    full_params = {"api_key": api_key, **params}
    try:
        resp = _requests.get(SAM_BASE_URL, params=full_params, timeout=timeout)
        if resp.status_code == 200:
            return resp.json()
        if resp.status_code == 429:
            time.sleep(10)
    except Exception:
        pass
    return None


def sam_lookup_by_name(vendor_name: str, api_key: str) -> dict | None:
    """
    Search SAM.gov by legal business name.
    Tries original name first, then normalized name.
    Returns result dict with UEI/CAGE/DUNS or None.
    """
    norm = normalize_vendor(vendor_name)
    search_names = [vendor_name]
    if norm != vendor_name:
        search_names.append(norm)

    for search_name in search_names:
        data = None
        for retry in range(RETRY_MAX):
            data = sam_call(
                {"legalBusinessName": search_name, "registrationStatus": "A", "page": 0, "size": 5},
                api_key,
            )
            if data is not None:
                break
            time.sleep(RETRY_DELAY * (retry + 1))

        if not data:
            continue

        entities = data.get("entityData", [])
        if not entities:
            continue

        best, best_score = None, 0.0
        for ent in entities:
            legal = ent.get("entityRegistration", {}).get("legalBusinessName", "")
            score = name_similarity(norm, normalize_vendor(legal))
            if score > best_score:
                best_score, best = score, ent

        if best and best_score >= MATCH_THRESHOLD:
            reg = best.get("entityRegistration", {})
            core = best.get("coreData", {})
            parent = best.get("parentEntityInfo", {})
            return {
                "uei": reg.get("ueiSAM", ""),
                "cage": reg.get("cageCode", ""),
                "duns": reg.get("dunsNumber", ""),
                "sam_name": reg.get("legalBusinessName", ""),
                "match_score": round(best_score, 3),
                "status": reg.get("registrationStatus", ""),
                "expiry": reg.get("registrationExpirationDate", ""),
                "state": core.get("physicalAddress", {}).get("stateOrProvinceCode", ""),
                "parent_uei": parent.get("ueiSAM", ""),
                "parent_name": parent.get("legalBusinessName", ""),
            }

    return None


def usaspending_lookup(vendor_name: str) -> dict | None:
    """POST to USASpending recipient search as fallback. Returns result dict or None."""
    norm = normalize_vendor(vendor_name)
    payload = json.dumps({
        "search_text": norm,
        "recipient_type_name": "business_types",
        "order": "desc",
        "sort": "amount",
        "limit": 5,
    }).encode()
    req = urllib.request.Request(
        USAS_BASE_URL,
        data=payload,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=6) as resp:
            if resp.status != 200:
                return None
            data = json.loads(resp.read().decode())
            results = data.get("results", [])
            if not results:
                return None
            best, best_score = None, 0.0
            for r in results:
                result_name = r.get("name") or r.get("recipient_name", "")
                score = name_similarity(norm, normalize_vendor(result_name))
                if score > best_score:
                    best_score, best = score, r
            if best and best_score >= MATCH_THRESHOLD:
                matched_name = best.get("name") or best.get("recipient_name", "")
                return {
                    "uei": best.get("uei", ""),
                    "duns": best.get("duns", ""),
                    "cage": "",
                    "sam_name": matched_name,
                    "match_score": round(best_score, 3),
                    "status": "USASPENDING",
                }
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Checkpoint / cache helpers
# ---------------------------------------------------------------------------

def _load_json(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            pass
    return {}


def _save_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _load_existing_index(index_path: Path) -> dict:
    results = {}
    if index_path.exists():
        with open(index_path) as f:
            for row in csv.DictReader(f):
                results[row["vendor_name"]] = row
    return results


# ---------------------------------------------------------------------------
# Target loading
# ---------------------------------------------------------------------------

def load_targets(root: Path) -> list[dict]:
    """
    Derive vendor targets from the master CSV.
    Aggregates by vendor_name: total obligated_amount and record count.
    Falls back to reading the master directly if vendor_targets.csv doesn't exist.
    Prefers pr_contracts_master.csv (vendor_name column); falls back to
    pr_all_awards_master.csv (recipient_name column).
    """
    targets_path = root / "data" / "staging" / "processed" / "vendor_targets.csv"
    master_path = root / "data" / "staging" / "processed" / "pr_contracts_master.csv"
    unified_path = root / "data" / "staging" / "processed" / "pr_all_awards_master.csv"

    if targets_path.exists():
        with open(targets_path) as f:
            rows = list(csv.DictReader(f))
        return [
            {
                "vendor_name": r["vendor_name"],
                "total_value": float(r.get("total_value", 0) or 0),
                "record_count": int(r.get("record_count", 1) or 1),
            }
            for r in rows if r.get("vendor_name", "").strip()
        ]

    # Determine which master to use and what the name column is called
    if master_path.exists():
        read_path = master_path
        name_col = "vendor_name"
    elif unified_path.exists():
        read_path = unified_path
        name_col = "recipient_name"
    else:
        raise FileNotFoundError(
            f"No master file found. Expected one of:\n"
            f"  {master_path}\n"
            f"  {unified_path}\n"
            "Run: python3 scripts/build_unified_master.py"
        )

    # Aggregate from master
    vendor_totals: dict[str, dict] = {}
    with open(read_path) as f:
        for row in csv.DictReader(f):
            vn = row.get(name_col, "").strip()
            if not vn:
                continue
            try:
                amt = float(row.get("obligated_amount", 0) or 0)
            except (ValueError, TypeError):
                amt = 0.0
            if vn not in vendor_totals:
                vendor_totals[vn] = {"total_value": 0.0, "record_count": 0}
            vendor_totals[vn]["total_value"] += amt
            vendor_totals[vn]["record_count"] += 1

    targets = [
        {"vendor_name": vn, **stats}
        for vn, stats in vendor_totals.items()
    ]
    targets.sort(key=lambda x: x["total_value"], reverse=True)

    # Write for reuse
    with open(targets_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["vendor_name", "total_value", "record_count"])
        w.writeheader()
        w.writerows(targets)

    return targets


# ---------------------------------------------------------------------------
# Index writer
# ---------------------------------------------------------------------------

def write_index(results: dict, output_dir: Path) -> None:
    fieldnames = [
        "vendor_name", "normalized_name", "total_value", "uei", "cage", "duns",
        "sam_name", "match_score", "status", "expiry", "state",
        "parent_uei", "parent_name",
        "source", "resolved_at",
    ]
    index_path = output_dir / "vendor_uei_index.csv"
    with open(index_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for r in sorted(results.values(), key=lambda x: float(x.get("total_value", 0)), reverse=True):
            w.writerow(r)


# ---------------------------------------------------------------------------
# Master merge
# ---------------------------------------------------------------------------

def merge_into_master(results: dict, root: Path, output_dir: Path, logger) -> None:
    """Patch master CSV with resolved UEI/CAGE/DUNS → master_enriched.csv."""
    master_path = root / "data" / "staging" / "processed" / "pr_contracts_master.csv"
    if not master_path.exists():
        logger.warning(f"  Master not found at {master_path} — skipping merge")
        return

    uei_map: dict[str, dict] = {}
    for vendor, row in results.items():
        if row.get("uei"):
            uei_map[vendor] = row
            uei_map[normalize_vendor(vendor)] = row

    with open(master_path) as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []
        rows = list(reader)

    for col in ("recipient_uei", "recipient_cage", "recipient_duns", "parent_uei", "parent_name"):
        if col not in fieldnames:
            fieldnames.append(col)

    patched = 0
    for row in rows:
        if row.get("recipient_uei"):
            continue
        vn = row.get("vendor_name", "").strip()
        match = uei_map.get(vn) or uei_map.get(normalize_vendor(vn))
        if match:
            row["recipient_uei"] = match.get("uei", "")
            row["recipient_cage"] = match.get("cage", "")
            row["recipient_duns"] = match.get("duns", "")
            row["parent_uei"] = match.get("parent_uei", "")
            row["parent_name"] = match.get("parent_name", "")
            patched += 1

    out_path = output_dir / "master_enriched.csv"
    with open(out_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    pct = patched / max(len(rows), 1) * 100
    logger.info(f"  Patched {patched:,}/{len(rows):,} master records ({pct:.1f}%) → {out_path.name}")


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def run(root: Path = None, resume: bool = False, dry_run: bool = False, top_n: int = None) -> dict:
    if root is None:
        root = PROJECT_ROOT

    output_dir = root / "data" / "staging" / "processed" / "enrichment"
    output_dir.mkdir(parents=True, exist_ok=True)

    logger = setup_logging("sam_enrichment")

    # Load API key (raises if missing)
    try:
        api_key = get_sam_api_key()
    except RuntimeError as e:
        logger.error(str(e))
        raise

    if dry_run:
        logger.info("[DRY RUN] Config validated.")
        logger.info(f"  SAM endpoint: {SAM_BASE_URL}")
        logger.info(f"  API key:      {api_key[:12]}...")
        logger.info(f"  Master path:  {root / 'data' / 'staging' / 'processed' / 'pr_contracts_master.csv'}")
        logger.info(f"  Output dir:   {output_dir}")
        return {"dry_run": True}

    logger.info("[INIT] Loading targets...")
    targets = load_targets(root)
    if top_n:
        targets = targets[:top_n]
        logger.info(f"[INIT] Capped to top {top_n} vendors by value")

    logger.info(f"[INIT] {len(targets):,} unique vendors to resolve")
    total_value = sum(t["total_value"] for t in targets)
    logger.info(f"[INIT] Total contract value: ${total_value:,.0f}")

    cache_path = output_dir / "sam_cache.json"
    checkpoint_path = output_dir / "checkpoint.json"
    index_path = output_dir / "vendor_uei_index.csv"
    fail_path = output_dir / "failed_lookups.csv"

    cache = _load_json(cache_path)
    results = _load_existing_index(index_path) if resume else {}
    checkpoint = _load_json(checkpoint_path) if resume else {}
    start_idx = checkpoint.get("last_idx", 0) if resume else 0

    if resume and start_idx > 0:
        logger.info(f"[RESUME] Resuming from vendor #{start_idx}")

    resolved = sum(1 for r in results.values() if r.get("uei"))
    failed = []
    processed = 0

    logger.info(f"[START] {datetime.now().isoformat()}")

    for i, target in enumerate(targets[start_idx:], start=start_idx):
        vendor = target["vendor_name"]
        norm = normalize_vendor(vendor)
        h = vendor_hash(vendor)

        if vendor in results and results[vendor].get("uei"):
            continue

        # Cache hit
        if h in cache:
            hit = cache[h]
            results[vendor] = {
                "vendor_name": vendor,
                "normalized_name": norm,
                "total_value": target["total_value"],
                **hit,
                "source": "cache",
                "resolved_at": datetime.now().isoformat(),
            }
            if hit.get("uei"):
                resolved += 1
            processed += 1
            continue

        # SAM primary lookup
        time.sleep(RATE_DELAY)
        sam_result = sam_lookup_by_name(vendor, api_key)
        source = "SAM"

        # USASpending fallback
        if not sam_result or not sam_result.get("uei"):
            usas_result = usaspending_lookup(vendor)
            if usas_result and usas_result.get("uei"):
                sam_result = usas_result
                source = "USASPENDING"

        if sam_result and sam_result.get("uei"):
            row = {
                "vendor_name": vendor,
                "normalized_name": norm,
                "total_value": target["total_value"],
                "source": source,
                "resolved_at": datetime.now().isoformat(),
                **sam_result,
            }
            results[vendor] = row
            cache[h] = sam_result
            resolved += 1
            logger.info(
                f"  [{i+1}/{len(targets)}] {vendor[:50]}\n"
                f"       UEI={sam_result['uei']} CAGE={sam_result.get('cage','')} "
                f"score={sam_result.get('match_score','')}"
            )
        else:
            results[vendor] = {
                "vendor_name": vendor,
                "normalized_name": norm,
                "total_value": target["total_value"],
                "uei": "", "cage": "", "duns": "",
                "sam_name": "", "match_score": 0,
                "status": "UNRESOLVED",
                "parent_uei": "", "parent_name": "",
                "source": "NONE",
                "resolved_at": datetime.now().isoformat(),
            }
            failed.append(vendor)
            logger.info(f"  [{i+1}/{len(targets)}] {vendor[:50]} — not resolved")

        processed += 1

        if processed % BATCH_SIZE == 0:
            write_index(results, output_dir)
            _save_json(cache_path, cache)
            _save_json(checkpoint_path, {
                "last_idx": i + 1,
                "resolved": resolved,
                "ts": datetime.now().isoformat(),
            })
            coverage = resolved / max(processed, 1)
            logger.info(
                f"  [CHECKPOINT] {resolved}/{processed} resolved ({coverage:.1%}) | "
                f"${sum(float(r.get('total_value', 0)) for r in results.values() if r.get('uei')):,.0f} covered"
            )

    # Final write
    write_index(results, output_dir)
    _save_json(cache_path, cache)

    if failed:
        with open(fail_path, "w", newline="") as f:
            csv.writer(f).writerow(["vendor_name"])
            for v in failed:
                csv.writer(f).writerow([v])

    merge_into_master(results, root, output_dir, logger)

    total_processed = len(targets) - start_idx
    coverage = resolved / max(total_processed, 1)
    value_resolved = sum(float(r.get("total_value", 0)) for r in results.values() if r.get("uei"))
    value_total = sum(t["total_value"] for t in targets)

    summary = {
        "run_ts": datetime.now().isoformat(),
        "vendors_attempted": total_processed,
        "vendors_resolved": resolved,
        "vendors_failed": len(failed),
        "coverage_pct": round(coverage * 100, 2),
        "value_resolved_usd": round(value_resolved, 2),
        "value_total_usd": round(value_total, 2),
        "value_coverage_pct": round(value_resolved / max(value_total, 1) * 100, 2),
        "coverage_gate_pass": coverage >= COVERAGE_GATE,
    }
    _save_json(output_dir / "enrichment_summary.json", summary)

    logger.info(f"\n{'=' * 60}")
    logger.info(f"[COMPLETE] {datetime.now().isoformat()}")
    logger.info(f"  Resolved:      {resolved:,} / {total_processed:,} ({coverage:.1%})")
    logger.info(f"  Value covered: ${value_resolved:,.0f} / ${value_total:,.0f} ({summary['value_coverage_pct']:.1f}%)")
    logger.info(f"  Gate:          {'PASS' if summary['coverage_gate_pass'] else 'FAIL — see failed_lookups.csv'}")

    if not summary["coverage_gate_pass"]:
        logger.warning(
            f"  Coverage {coverage:.1%} below gate ({COVERAGE_GATE:.0%}). "
            f"Check {fail_path} for manual resolution."
        )

    return summary


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SAM.gov UEI batch enrichment")
    parser.add_argument("--resume", action="store_true", help="Resume from checkpoint")
    parser.add_argument("--dry-run", action="store_true", help="Validate config only, no API calls")
    parser.add_argument("--top", type=int, metavar="N", help="Only enrich top N vendors by value")
    args = parser.parse_args()

    summary = run(resume=args.resume, dry_run=args.dry_run, top_n=args.top)
    sys.exit(0 if summary.get("dry_run") or summary.get("coverage_gate_pass") else 1)
