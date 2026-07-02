"""FTA National Transit Database (NTD) producer — Socrata SODA API.

Fetches PR transit-agency financial / funding / operating-expense data from the FTA
NTD datasets hosted on ``data.transportation.gov`` (a Socrata portal) and materializes
``data/staging/processed/pr_fta_ntd.csv``. PR agencies (PRHTA, PRITA, Ports Authority)
are NTD reporters, so PR rows are present in the annual data products.

Socrata SODA (no key required for moderate use; an app token may be set via
``DATA_GOV_API_KEY``): ``GET {base}/resource/{id}.json?$limit=&$offset=`` returns a JSON
array of record objects. Records are filtered to Puerto Rico and projected onto a tolerant
canonical schema.

No-egress safe: any HTTP/network failure writes an empty-schema CSV and returns
``status="EMPTY"`` without raising — the readiness preflight imports this module without
touching the network.

NOTE: ``NTD_RESOURCE_ID`` is the one value the first live run must confirm against the
current NTD data product on data.transportation.gov; the SODA fetch/normalize logic is
standard and exercised by mocked tests.

Usage:
  python3 scripts/download_fta_ntd.py
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

SODA_BASE = "https://data.transportation.gov"
# Best-effort default NTD annual data-product resource id; confirm on first live run.
NTD_RESOURCE_ID = os.environ.get("NTD_RESOURCE_ID", "")
USER_AGENT = "ContractSweeper/1.0 (+https://github.com/jotaele44/moneysweep-pr)"
PAGE_LIMIT = 1000
MAX_RECORDS = 200_000
MAX_RETRIES = 3
RETRY_BACKOFF = (5, 15, 30)
OUTPUT = "data/staging/processed/pr_fta_ntd.csv"

CANONICAL_COLUMNS = ["period", "category", "amount_usd", "source_system"]

PERIOD_ALIASES = ("report_year", "year", "ntd_report_year", "fy", "period")
CATEGORY_ALIASES = ("agency", "agency_name", "ntd_id", "mode", "type_of_service", "uace_name")
AMOUNT_ALIASES = (
    "operating_expenses",
    "total_operating_expenses",
    "total_funding",
    "federal_funding",
    "fares",
    "amount",
    "total",
)
# Fields scanned to keep only Puerto Rico rows.
STATE_FIELDS = ("state", "uace_name", "agency", "agency_name", "city")


def _session() -> requests.Session:
    s = requests.Session()
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    # Data.gov-family sites share the api.data.gov key; fall back to X_API_KEY
    # when the source-specific DATA_GOV_API_KEY is not set.
    token = (
        os.environ.get("DATA_GOV_API_KEY", "").strip() or os.environ.get("X_API_KEY", "").strip()
    )
    if token:
        headers["X-App-Token"] = token
    s.headers.update(headers)
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


def _is_pr(record: dict) -> bool:
    for f in STATE_FIELDS:
        v = str(record.get(f, "")).lower()
        if v in ("pr", "puerto rico") or "puerto rico" in v:
            return True
    return False


def fetch_records(session, base: str, resource_id: str, logger) -> list[dict]:
    if not resource_id:
        logger.warning("  NTD_RESOURCE_ID not set — cannot resolve dataset; returning none")
        return []
    url = f"{base}/resource/{resource_id}.json"
    rows: list[dict] = []
    offset = 0
    while offset < MAX_RECORDS:
        batch = _get_json(session, url, {"$limit": PAGE_LIMIT, "$offset": offset}, logger)
        if not batch:
            break
        rows.extend(batch)
        offset += len(batch)
        if len(batch) < PAGE_LIMIT:
            break
        time.sleep(0.3)
    return [r for r in rows if isinstance(r, dict) and _is_pr(r)]


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
            "source_system": "fta_ntd",
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
    logger = setup_logging("download_fta_ntd")
    out_path = root / OUTPUT
    session = _session()
    try:
        records = fetch_records(session, SODA_BASE, NTD_RESOURCE_ID, logger)
    finally:
        session.close()
    rows = normalize(records)
    _write_csv(rows, out_path)
    status = "OK" if rows else "EMPTY"
    logger.info(f"  fta_ntd: {len(rows)} PR rows — {status}")
    return {"rows": len(rows), "status": status, "path": str(out_path)}


main = run
download = run
fetch = run


def _cli(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(description=__doc__).parse_args(argv)
    result = run()
    print(f"fta_ntd: {result['rows']:,} rows — {result['status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
