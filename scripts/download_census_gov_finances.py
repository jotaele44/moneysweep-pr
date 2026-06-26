"""Census government-finance producer — Census Data API (2D-array JSON).

Fetches PR (FIPS 72) government-finance / tax-collection figures from the Census Data
API and materializes ``data/staging/processed/pr_census_gov_finances.csv``.

Census Data API format: ``GET {base}/data/{dataset}?get={vars}&for=state:72&key={KEY}``
returns a 2-D JSON array whose first row is the header and the rest are records. Needs
``CENSUS_API_KEY``.

CAVEAT: the Census Bureau notes that Puerto Rico (FIPS 72) is **not included in most
Census API datasets**. This producer queries the documented endpoint and, if PR is absent
from the chosen dataset, returns ``EMPTY`` gracefully rather than fabricating rows. The
dataset path + variable list (``CENSUS_DATASET`` / ``CENSUS_VARS``) are best-effort and
must be confirmed against the API discovery tool on the first live run; the fetch/parse
logic is standard and exercised by mocked tests.

No-egress safe: any HTTP/network failure (incl. missing key) writes an empty-schema CSV
and returns ``status="EMPTY"`` without raising.

Usage:
  python3 scripts/download_census_gov_finances.py
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests

from scripts.config import PROJECT_ROOT, setup_logging

CENSUS_BASE = "https://api.census.gov"
# Best-effort dataset + variables (confirm on first live run via the API discovery tool).
CENSUS_DATASET = os.environ.get("CENSUS_DATASET", "data/timeseries/govs")
CENSUS_VARS = os.environ.get("CENSUS_VARS", "NAME,AMOUNT,AGG_DESC")
USER_AGENT = "ContractSweeper/1.0 (+https://github.com/jotaele44/moneysweep-pr)"
MAX_RETRIES = 3
RETRY_BACKOFF = (5, 15, 30)
OUTPUT = "data/staging/processed/pr_census_gov_finances.csv"

CANONICAL_COLUMNS = ["period", "category", "amount_usd", "source_system"]

PERIOD_ALIASES = ("year", "time", "period", "ano")
CATEGORY_ALIASES = ("agg_desc", "category", "name", "tax_desc", "description", "label")
AMOUNT_ALIASES = ("amount", "amt", "value", "estimate", "total")


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})
    return s


def _get_json(session, url, params, logger):
    for attempt in range(MAX_RETRIES):
        try:
            resp = session.get(url, params=params, timeout=60)
            if resp.status_code == 429:
                logger.warning("  Rate limited — sleeping 60s")
                time.sleep(60)
                continue
            if 400 <= resp.status_code < 500:
                logger.warning(f"  HTTP {resp.status_code} for {url}")
                return None
            resp.raise_for_status()
            return resp.json()
        except (requests.RequestException, ValueError) as exc:
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_BACKOFF[attempt])
            else:
                logger.warning(f"  All {MAX_RETRIES} attempts failed for {url}: {exc}")
    return None


def _rows_from_2d(payload) -> list[dict]:
    """Census returns [[header...],[row...],...] — convert to a list of dicts."""
    if not isinstance(payload, list) or len(payload) < 2:
        return []
    header = [str(h) for h in payload[0]]
    return [dict(zip(header, row)) for row in payload[1:] if isinstance(row, list)]


def _pick(record: dict, aliases: tuple[str, ...]) -> str:
    lower = {str(k).strip().lower(): v for k, v in record.items()}
    for alias in aliases:
        if alias in lower and lower[alias] not in (None, ""):
            return str(lower[alias]).strip()
    return ""


def _clean_amount(value: str) -> str:
    s = value.replace("$", "").replace(",", "").strip()
    if s in ("", "-", "—"):
        return ""
    try:
        return str(float(s))
    except ValueError:
        return ""


def normalize(records: list[dict]) -> list[dict]:
    out: list[dict] = []
    for rec in records:
        if not isinstance(rec, dict):
            continue
        row = {
            "period": _pick(rec, PERIOD_ALIASES),
            "category": _pick(rec, CATEGORY_ALIASES),
            "amount_usd": _clean_amount(_pick(rec, AMOUNT_ALIASES)),
            "source_system": "census_gov_finances",
        }
        if not row["category"] and not row["amount_usd"]:
            continue
        out.append(row)
    out.sort(key=lambda r: (r["period"], r["category"], r["amount_usd"]))
    return out


def _write_csv(rows: list[dict], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CANONICAL_COLUMNS, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def run(root: Path | None = None) -> dict:
    root = Path(root or PROJECT_ROOT)
    logger = setup_logging("download_census_gov_finances")
    out_path = root / OUTPUT
    key = os.environ.get("CENSUS_API_KEY", "").strip()
    records: list[dict] = []
    if not key:
        logger.warning("  CENSUS_API_KEY not set — skipping (EMPTY)")
    else:
        session = _session()
        try:
            payload = _get_json(
                session,
                f"{CENSUS_BASE}/{CENSUS_DATASET}",
                {"get": CENSUS_VARS, "for": "state:72", "key": key},
                logger,
            )
            records = _rows_from_2d(payload)
        finally:
            session.close()
    rows = normalize(records)
    _write_csv(rows, out_path)
    status = "OK" if rows else "EMPTY"
    logger.info(f"  census_gov_finances: {len(rows)} PR rows — {status}")
    return {"rows": len(rows), "status": status, "path": str(out_path)}


main = run
download = run
fetch = run


def _cli(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(description=__doc__).parse_args(argv)
    result = run()
    print(f"census_gov_finances: {result['rows']:,} rows — {result['status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
