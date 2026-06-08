"""Extract parent_uei for every unique UEI using USAspending.gov recipient API.

No API key required. No daily rate limit.

For each unique recipient_uei in staged award CSVs:
  1. POST /api/v2/recipient/ with keyword=<uei> → get recipient hash
  2. GET /api/v2/recipient/<hash>/ → get parent_uei, parent_name

Writes:
  data/staging/processed/enrichment/usaspending_parent_index.csv
  (resume-safe: skips already-resolved UEIs)

Usage:
  python3 scripts/usaspending_parent_uei_extract.py
  python3 scripts/usaspending_parent_uei_extract.py --dry-run
  python3 scripts/usaspending_parent_uei_extract.py --limit 200
  python3 scripts/usaspending_parent_uei_extract.py --force
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROCESSED_DIR = PROJECT_ROOT / "data" / "staging" / "processed"
ENRICHMENT_DIR = PROCESSED_DIR / "enrichment"
OUTPUT_CSV = ENRICHMENT_DIR / "usaspending_parent_index.csv"

USAS_SEARCH = "https://api.usaspending.gov/api/v2/recipient/"
SLEEP = 0.4  # ~2.5 req/s → well under any practical limit
MAX_RETRIES = 3

OUTPUT_FIELDS = [
    "uei",
    "usas_name",
    "recipient_hash",
    "parent_uei",
    "parent_name",
    "parent_duns",
    "resolved_at",
]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(
            PROJECT_ROOT / "data" / "logs" / "usaspending_parent_extract.log",
            encoding="utf-8",
        ),
    ],
)
log = logging.getLogger(__name__)


def _collect_ueis() -> list[str]:
    ueis: set[str] = set()
    for name in (
        "pr_all_awards_master.csv",
        "pr_subawards_master.csv",
        "pr_fema_pa_master.csv",
        "pr_fec_contributions.csv",
    ):
        p = PROCESSED_DIR / name
        if not p.exists():
            continue
        try:
            with p.open(encoding="utf-8-sig", newline="") as f:
                for row in csv.DictReader(f):
                    for col in ("recipient_uei", "uei", "entity_uei", "prime_uei", "sub_uei"):
                        v = (row.get(col) or "").strip()
                        if v and len(v) == 12:
                            ueis.add(v)
        except Exception as exc:
            log.warning(f"could not read {name}: {exc}")
    return sorted(ueis)


def _post(url: str, body: dict) -> dict | None:
    payload = json.dumps(body).encode()
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    for attempt in range(MAX_RETRIES):
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                wait = [10, 30, 60][min(attempt, 2)]
                log.warning(f"rate-limited, sleeping {wait}s")
                time.sleep(wait)
            elif exc.code >= 500:
                time.sleep(5 * (attempt + 1))
            else:
                return None
        except Exception as exc:
            log.warning(f"POST error (attempt {attempt + 1}): {exc}")
            if attempt < MAX_RETRIES - 1:
                time.sleep(3)
    return None


def _get(url: str) -> dict | None:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    for attempt in range(MAX_RETRIES):
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as exc:
            if exc.code in (404, 400):
                return None
            if exc.code == 429:
                wait = [10, 30, 60][min(attempt, 2)]
                log.warning(f"rate-limited on GET, sleeping {wait}s")
                time.sleep(wait)
            else:
                time.sleep(5 * (attempt + 1))
        except Exception as exc:
            log.warning(f"GET error (attempt {attempt + 1}): {exc}")
            if attempt < MAX_RETRIES - 1:
                time.sleep(3)
    return None


def _lookup_uei(uei: str) -> dict:
    """Search USAspending for UEI, get recipient hash, then fetch parent info."""
    # Step 1: search by UEI keyword
    search_data = _post(USAS_SEARCH, {"keyword": uei, "limit": 5})
    if not search_data:
        return {"uei": uei, "resolved_at": datetime.now(timezone.utc).isoformat()}

    results = search_data.get("results", [])
    exact = [r for r in results if r.get("uei") == uei]
    if not exact:
        return {"uei": uei, "resolved_at": datetime.now(timezone.utc).isoformat()}

    best = exact[0]
    hash_id = best.get("id", "")
    usas_name = best.get("name", "")
    time.sleep(SLEEP)

    # Step 2: fetch profile for parent info
    profile = _get(f"{USAS_SEARCH}{hash_id}/") if hash_id else None
    parent_uei = parent_name = parent_duns = ""
    if profile:
        parent_uei = profile.get("parent_uei") or ""
        parent_name = profile.get("parent_name") or ""
        parent_duns = profile.get("parent_duns") or ""

    return {
        "uei": uei,
        "usas_name": usas_name,
        "recipient_hash": hash_id,
        "parent_uei": parent_uei,
        "parent_name": parent_name,
        "parent_duns": parent_duns,
        "resolved_at": datetime.now(timezone.utc).isoformat(),
    }


def _load_existing() -> dict[str, dict]:
    if not OUTPUT_CSV.exists():
        return {}
    result: dict[str, dict] = {}
    try:
        with OUTPUT_CSV.open(encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                uei = row.get("uei", "").strip()
                if uei:
                    result[uei] = row
    except Exception:
        pass
    return result


def _flush(rows: list[dict]) -> None:
    if not rows:
        return
    ENRICHMENT_DIR.mkdir(parents=True, exist_ok=True)
    with OUTPUT_CSV.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=OUTPUT_FIELDS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in OUTPUT_FIELDS})


def run(*, force: bool = False, dry_run: bool = False, limit: int | None = None) -> dict:
    (PROJECT_ROOT / "data" / "logs").mkdir(parents=True, exist_ok=True)
    ueis = _collect_ueis()
    log.info(f"[INIT] {len(ueis)} unique UEIs collected")

    if dry_run:
        return {"uei_count": len(ueis), "dry_run": True}

    existing = _load_existing() if not force else {}
    log.info(f"[RESUME] {len(existing)} already done, {len(ueis) - len(existing)} remaining")

    todo = [u for u in ueis if u not in existing]
    if limit:
        todo = todo[:limit]

    resolved = dict(existing)
    checkpoint_every = 100

    for i, uei in enumerate(todo, 1):
        result = _lookup_uei(uei)
        resolved[uei] = result
        parent = result.get("parent_uei")
        log.info(
            f"  [{i}/{len(todo)}] {uei} → {result.get('usas_name', '')[:35]}"
            f" parent={parent or 'none'}"
        )
        time.sleep(SLEEP)

        if i % checkpoint_every == 0:
            _flush(list(resolved.values()))
            parent_rate = sum(1 for r in resolved.values() if r.get("parent_uei")) / max(
                len(resolved), 1
            )
            log.info(f"  [CHECKPOINT] {len(resolved)} done, parent_uei rate={parent_rate:.1%}")

    _flush(list(resolved.values()))

    total = len(resolved)
    parent_count = sum(1 for r in resolved.values() if r.get("parent_uei"))
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "ueis_queried": len(ueis),
        "usas_found": sum(1 for r in resolved.values() if r.get("usas_name")),
        "parent_uei_resolved": parent_count,
        "parent_uei_rate": round(parent_count / max(total, 1), 4),
        "output": str(OUTPUT_CSV.relative_to(PROJECT_ROOT)),
    }
    log.info(f"[DONE] {json.dumps(summary)}")
    return summary


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--force", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--limit", type=int)
    a = p.parse_args(argv)
    result = run(force=a.force, dry_run=a.dry_run, limit=a.limit)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
