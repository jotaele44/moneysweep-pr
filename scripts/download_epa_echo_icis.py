"""EPA ECHO / ICIS-FE&C producer — Enforcement & Compliance REST API.

Fetches PR environmental enforcement cases (the financial signal: federal penalties
assessed) from EPA's ECHO Enforcement Case Search REST API and materializes
``data/staging/processed/pr_epa_echo_icis.csv``. Serves the registry source
``eqb_epa_icis`` (PR Environmental Quality Board / EPA ICIS enforcement).

ECHO is a public, keyless REST API. ``X_API_KEY`` (an api.data.gov rate-limit key) is sent
as the ``X-Api-Key`` header opportunistically when set, but the producer works without it.

  GET https://echodata.epa.gov/echo/case_rest_services.get_cases?output=JSON&p_st=PR

Response shape varies; a tolerant extractor locates the results list and an alias map
projects records onto the canonical schema.

No-egress safe: any HTTP/network failure writes an empty-schema CSV and returns
``status="EMPTY"`` without raising — the readiness preflight imports this module without
touching the network.

NOTE: the exact endpoint + field names are confirmed on the first live run; the
fetch/parse logic is standard and exercised by mocked tests.

Usage:
  python3 scripts/download_epa_echo_icis.py
"""

from __future__ import annotations

import argparse
import os
import csv
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests

from scripts.config import PROJECT_ROOT, setup_logging

ECHO_BASE = "https://echodata.epa.gov/echo"
ECHO_ENDPOINT = os.environ.get("ECHO_ENDPOINT", "case_rest_services.get_cases")
USER_AGENT = "ContractSweeper/1.0 (+https://github.com/jotaele44/moneysweep-pr)"
MAX_RETRIES = 3
RETRY_BACKOFF = (5, 15, 30)
OUTPUT = "data/staging/processed/pr_epa_echo_icis.csv"

CANONICAL_COLUMNS = ["period", "category", "amount_usd", "source_system"]

PERIOD_ALIASES = (
    "enf_concluded_date",
    "settled_date",
    "fy",
    "fiscal_year",
    "year",
    "case_concluded_year",
)
CATEGORY_ALIASES = (
    "defendant_entity",
    "fac_name",
    "facility_name",
    "case_name",
    "statutes",
    "statute",
    "category",
)
AMOUNT_ALIASES = (
    "fed_penalty_assessed_amt",
    "federal_penalty",
    "total_penalty_assessed_amt",
    "total_penalty",
    "penalty",
    "amount",
)
# Keys that may hold the list of result records in ECHO's JSON envelope.
_RESULT_KEYS = ("Cases", "Facilities", "Results", "results", "data")


def _session() -> requests.Session:
    s = requests.Session()
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    key = os.environ.get("X_API_KEY", "").strip()
    if key:
        headers["X-Api-Key"] = key
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


def extract_records(payload) -> list[dict]:
    """Tolerantly locate the list of case/facility records in ECHO's JSON envelope."""
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict)]
    if not isinstance(payload, dict):
        return []
    # Common ECHO shape: {"Results": {"Cases": [...]}} — walk one or two levels.
    for key in _RESULT_KEYS:
        val = payload.get(key)
        if isinstance(val, list):
            return [r for r in val if isinstance(r, dict)]
        if isinstance(val, dict):
            for k2 in _RESULT_KEYS:
                inner = val.get(k2)
                if isinstance(inner, list):
                    return [r for r in inner if isinstance(r, dict)]
    return []


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
            "source_system": "eqb_epa_icis",
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
    logger = setup_logging("download_epa_echo_icis")
    out_path = root / OUTPUT
    session = _session()
    try:
        payload = _get_json(
            session,
            f"{ECHO_BASE}/{ECHO_ENDPOINT}",
            {"output": "JSON", "p_st": "PR"},
            logger,
        )
    finally:
        session.close()
    rows = normalize(extract_records(payload))
    _write_csv(rows, out_path)
    status = "OK" if rows else "EMPTY"
    logger.info(f"  eqb_epa_icis: {len(rows)} PR enforcement rows — {status}")
    return {"rows": len(rows), "status": status, "path": str(out_path)}


main = run
download = run
fetch = run


def _cli(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(description=__doc__).parse_args(argv)
    result = run()
    print(f"eqb_epa_icis: {result['rows']:,} rows — {result['status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
