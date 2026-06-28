"""SAM.gov UEI → parent_uei bulk lookup.

Extracts unique recipient_ueis from staged award CSVs, queries the SAM
entity-information API v3 by UEI (not by name), and writes:
  data/staging/processed/sam_entities.csv
  data/staging/processed/sam_entities.parquet  (if pyarrow available)

Parent UEI resolution via SAM is far more accurate than name-based lookup
because the UEI is a stable identifier, not a fuzzy string.

Never prints or logs the API key.

Usage:
  python3 scripts/sam_uei_parent_lookup.py
  python3 scripts/sam_uei_parent_lookup.py --force        # re-query even if output exists
  python3 scripts/sam_uei_parent_lookup.py --dry-run      # extract UEIs only, no API calls
  python3 scripts/sam_uei_parent_lookup.py --limit 100    # cap queries (for testing)
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROCESSED_DIR = PROJECT_ROOT / "data" / "staging" / "processed"


def _get_sam_api_key() -> str:
    """Load SAM_API_KEY from env or .env file. Never log the value."""
    key = os.environ.get("SAM_API_KEY", "").strip()
    if key:
        return key
    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("SAM_API_KEY="):
                k = line.split("=", 1)[1].strip()
                if k:
                    return k
    raise RuntimeError(
        "SAM_API_KEY not set. Create .env with: SAM_API_KEY=your_key\n"
        "Get a free key at https://sam.gov/data-services"
    )


SAM_ENTITY_URL = "https://api.sam.gov/entity-information/v2/entities"
PAGE_SIZE = 1  # one UEI per call; batch endpoint not available on free tier
SLEEP_KEY = 0.25  # 4 req/s with API key → well under 1000/hr limit
SLEEP_NO_KEY = 3.0  # 20 req/min without key → conservative
MAX_RETRIES = 3
RETRY_BACKOFF = [5, 15, 30]

# Fields to harvest from SAM response
SAM_OUTPUT_FIELDS = [
    "uei",
    "sam_legal_name",
    "cage",
    "duns",
    "status",
    "expiry",
    "state",
    "country",
    "immediate_parent_uei",
    "immediate_parent_name",
    "ultimate_parent_uei",
    "ultimate_parent_name",
    "entity_type",
    "business_type_codes",
    "resolved_at",
]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(
            PROJECT_ROOT / "data" / "logs" / "sam_uei_parent_lookup.log", encoding="utf-8"
        ),
    ],
)
log = logging.getLogger(__name__)


def _collect_ueis(root: Path) -> list[str]:
    """Return unique 12-char UEIs to enrich.

    Prefers ``enrichment/vendor_uei_index.csv`` (produced by
    ``build_uei_index_from_source.py``), reading it **in file order** — that file
    is sorted by total obligated value descending, so a quota-limited daily run
    enriches the highest-value vendors first. Falls back to scanning the staged
    award masters when the index is absent.
    """
    index_path = root / "data" / "staging" / "processed" / "enrichment" / "vendor_uei_index.csv"
    if index_path.exists():
        ordered: list[str] = []
        seen: set[str] = set()
        try:
            with index_path.open(encoding="utf-8-sig", newline="") as f:
                for row in csv.DictReader(f):
                    v = (row.get("uei") or "").strip()
                    if len(v) == 12 and v not in seen:
                        seen.add(v)
                        ordered.append(v)
            log.info(f"[SOURCE] {len(ordered)} UEIs from vendor_uei_index.csv (value-sorted)")
            return ordered
        except Exception as e:
            log.warning(f"could not read {index_path.name}: {e} — falling back to master scan")

    ueis: set[str] = set()
    targets = [
        root / "data" / "staging" / "processed" / "pr_all_awards_master.csv",
        root / "data" / "staging" / "processed" / "pr_subawards_master.csv",
        root / "data" / "staging" / "processed" / "pr_fema_pa_master.csv",
    ]
    for path in targets:
        if not path.exists():
            continue
        try:
            with path.open(encoding="utf-8-sig", newline="") as f:
                for row in csv.DictReader(f):
                    for col in (
                        "recipient_uei",
                        "uei",
                        "entity_uei",
                        "prime_uei",
                        "sub_uei",
                        "Recipient UEI",
                    ):
                        v = (row.get(col) or "").strip()
                        if v and len(v) == 12:  # SAM UEIs are always 12 chars
                            ueis.add(v)
        except Exception as e:
            log.warning(f"could not read {path.name}: {e}")
    return sorted(ueis)


class _QuotaExhausted(Exception):
    """SAM daily request quota spent (HTTP 429, code 900804). Further calls today
    are futile until 00:00 UTC, so the run should flush and stop cleanly."""

    def __init__(self, next_access_time: str = ""):
        self.next_access_time = next_access_time
        super().__init__(f"SAM daily quota exhausted; resets {next_access_time or '00:00 UTC'}")


def _query_sam(uei: str, api_key: str) -> dict | None:
    """Query SAM entity-information v2 for a single UEI. Returns parsed entity dict or None.

    Raises :class:`_QuotaExhausted` on a daily-quota 429 (code 900804) so the run
    loop can stop cleanly instead of backing off on every remaining UEI."""
    import urllib.request
    import urllib.parse
    import urllib.error

    params = urllib.parse.urlencode(
        {
            "ueiSAM": uei,
            "api_key": api_key,
        }
    )
    url = f"{SAM_ENTITY_URL}?{params}"
    for attempt in range(MAX_RETRIES):
        try:
            req = urllib.request.Request(url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            entities = data.get("entityData", [])
            if not entities:
                return None
            e = entities[0]
            reg = e.get("entityRegistration", {}) or {}
            core = e.get("coreData", {}) or {}
            # v2: parent info is at root level under parentEntityInfo
            parent = e.get("parentEntityInfo", {}) or {}
            addr = core.get("physicalAddress") or core.get("mailingAddress") or {}
            biz = core.get("businessTypes", {}) or {}
            btypes = biz.get("businessTypeList", []) or []
            return {
                "uei": reg.get("ueiSAM", uei),
                "sam_legal_name": reg.get("legalBusinessName", ""),
                "cage": reg.get("cageCode", ""),
                "duns": reg.get("dunsNumber", ""),
                "status": reg.get("registrationStatus", ""),
                "expiry": reg.get("registrationExpirationDate", ""),
                "state": addr.get("stateOrProvinceCode", ""),
                "country": addr.get("countryCode", ""),
                "immediate_parent_uei": parent.get("ueiSAM", ""),
                "immediate_parent_name": parent.get("legalBusinessName", ""),
                "ultimate_parent_uei": parent.get("ultimateParentUEI", ""),
                "ultimate_parent_name": parent.get("ultimateParentName", ""),
                "entity_type": reg.get("entityStructureCode", ""),
                "business_type_codes": ";".join(
                    bt.get("businessTypeCode", "") for bt in btypes if bt.get("businessTypeCode")
                ),
                "resolved_at": datetime.now(timezone.utc).isoformat(),
            }
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                # Distinguish daily-quota exhaustion (900804) from a transient throttle.
                try:
                    body = json.loads(exc.read().decode("utf-8"))
                except Exception:
                    body = {}
                msg = str(body.get("message", "")).lower()
                if str(body.get("code")) == "900804" or "exceeded your quota" in msg:
                    raise _QuotaExhausted(str(body.get("nextAccessTime", "")))
                wait = RETRY_BACKOFF[min(attempt, len(RETRY_BACKOFF) - 1)]
                log.warning(f"rate-limited on {uei}, sleeping {wait}s")
                time.sleep(wait)
            elif exc.code in (404, 400):
                return None
            else:
                log.warning(f"HTTP {exc.code} for {uei} (attempt {attempt + 1})")
                if attempt < MAX_RETRIES - 1:
                    time.sleep(RETRY_BACKOFF[attempt])
        except Exception as exc:
            log.warning(f"error for {uei} (attempt {attempt + 1}): {exc}")
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_BACKOFF[attempt])
    return None


def _load_existing(out_csv: Path) -> dict[str, dict]:
    """Load already-resolved UEIs from output CSV to resume interrupted runs."""
    if not out_csv.exists():
        return {}
    result: dict[str, dict] = {}
    try:
        with out_csv.open(encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                uei = row.get("uei", "").strip()
                if uei:
                    result[uei] = row
    except Exception:
        pass
    return result


def run(
    root: Path,
    *,
    force: bool = False,
    dry_run: bool = False,
    limit: int | None = None,
) -> dict:
    out_csv = root / "data" / "staging" / "processed" / "sam_entities.csv"
    log_dir = root / "data" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    ueis = _collect_ueis(root)
    log.info(f"[INIT] {len(ueis)} unique UEIs collected")

    if not ueis:
        log.warning(
            "No UEIs found — nothing to enrich. This needs the generated vendor index, "
            "which is gitignored and not in a fresh clone. Provide it first, e.g.:\n"
            "  data/staging/processed/enrichment/vendor_uei_index.csv  (drop in if you have it), or\n"
            "  python3 scripts/build_uei_index_from_source.py          (rebuild from the master), or\n"
            "  run the pipeline: auto_download.py → normalize_expansion_inputs.py → "
            "deduplicate_master.py → build_uei_index_from_source.py"
        )

    if dry_run:
        return {"uei_count": len(ueis), "dry_run": True}

    api_key: str
    try:
        api_key = _get_sam_api_key()
        sleep_between = SLEEP_KEY
    except RuntimeError as exc:
        log.error(str(exc))
        return {"error": "SAM_API_KEY not available", "uei_count": len(ueis)}

    # Resume support: skip already-resolved
    existing = _load_existing(out_csv) if not force else {}
    log.info(f"[RESUME] {len(existing)} already resolved, {len(ueis) - len(existing)} remaining")

    todo = [u for u in ueis if u not in existing]
    if limit:
        todo = todo[:limit]

    resolved = dict(existing)
    not_found = []
    checkpoint_every = 50

    quota_exhausted = False
    for i, uei in enumerate(todo, 1):
        try:
            result = _query_sam(uei, api_key)
        except _QuotaExhausted as e:
            _flush_csv(out_csv, list(resolved.values()))
            log.warning(
                f"  [QUOTA] SAM daily quota exhausted after {i - 1} queries this run "
                f"({len(resolved)} total resolved). Resets {e.next_access_time or '00:00 UTC'}. "
                f"Re-run to resume — already-resolved UEIs are skipped."
            )
            quota_exhausted = True
            break
        if result:
            resolved[uei] = result
            parent = result.get("immediate_parent_uei") or result.get("ultimate_parent_uei")
            log.info(
                f"  [{i}/{len(todo)}] {uei} → {result['sam_legal_name'][:40]}"
                f" parent={parent or 'none'}"
            )
        else:
            not_found.append(uei)
            log.info(f"  [{i}/{len(todo)}] {uei} — not found in SAM")
        time.sleep(sleep_between)

        if i % checkpoint_every == 0:
            _flush_csv(out_csv, list(resolved.values()))
            pct = sum(
                1
                for r in resolved.values()
                if r.get("immediate_parent_uei") or r.get("ultimate_parent_uei")
            ) / max(len(resolved), 1)
            log.info(f"  [CHECKPOINT] {len(resolved)} resolved, parent_uei rate={pct:.1%}")

    _flush_csv(out_csv, list(resolved.values()))

    # Also write parquet if pyarrow available and rows exist
    if resolved:
        try:
            import pyarrow.csv as pac
            import pyarrow.parquet as pq

            t = pac.read_csv(str(out_csv))
            pq.write_table(t, str(out_csv.with_suffix(".parquet")))
            log.info(f"wrote {out_csv.with_suffix('.parquet')}")
        except ImportError:
            pass
        except Exception as exc:
            log.warning(f"parquet write failed: {exc}")

    parent_resolved = sum(
        1
        for r in resolved.values()
        if r.get("immediate_parent_uei") or r.get("ultimate_parent_uei")
    )
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "ueis_queried": len(ueis),
        "sam_resolved": len(resolved),
        "not_found_in_sam": len(not_found),
        "parent_uei_resolved": parent_resolved,
        "parent_uei_rate": round(parent_resolved / max(len(resolved), 1), 4),
        "quota_exhausted": quota_exhausted,
        "output": str(out_csv.relative_to(root)),
    }
    log.info(f"[DONE] {json.dumps(summary)}")
    return summary


def _flush_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=SAM_OUTPUT_FIELDS, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow({k: row.get(k, "") for k in SAM_OUTPUT_FIELDS})


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", type=Path, default=PROJECT_ROOT)
    p.add_argument("--force", action="store_true", help="re-query even if output exists")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--limit", type=int, help="cap number of UEIs queried")
    a = p.parse_args(argv)
    result = run(Path(a.root), force=a.force, dry_run=a.dry_run, limit=a.limit)
    print(json.dumps(result, indent=2))
    return 0 if "error" not in result else 1


if __name__ == "__main__":
    raise SystemExit(main())
