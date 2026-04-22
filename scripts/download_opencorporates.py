"""
Download Puerto Rico business entity registrations from OpenCorporates.

OpenCorporates aggregates corporate registry data from government sources.
For Puerto Rico (jurisdiction us_pr), this includes corporations, LLCs, and
other entities registered with the Puerto Rico Department of State.

Cross-references against the unified awards master to surface:
  - Corporate officers of award-receiving entities
  - Registered agents (who controls the entity)
  - Parent/subsidiary relationships via shared officers
  - Inactive/dissolved entities still receiving awards

Outputs:
  data/staging/processed/pr_opencorporates_companies.csv  — all PR-registered entities
  data/staging/processed/pr_opencorporates_officers.csv   — officers for matched entities

Usage:
  python3 scripts/download_opencorporates.py [--force] [--api-token TOKEN]
  # TOKEN from env var OPENCORPORATES_API_TOKEN if not provided
"""

import argparse
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import requests

from scripts.config import PROCESSED_DIR, PROJECT_ROOT, setup_logging

OC_BASE       = "https://api.opencorporates.com/v0.4"
JURISDICTION  = "us_pr"
PER_PAGE      = 100          # max per request
PAGE_SLEEP    = 0.5
MAX_RETRIES   = 3
RETRY_BACKOFF = [5, 15, 30]
MAX_PAGES     = 2000         # safety cap; PR registry unlikely to exceed 200k companies

COMPANY_COLUMNS = [
    "company_number", "name", "jurisdiction_code", "company_type",
    "incorporation_date", "dissolution_date", "current_status",
    "registered_address", "agent_name", "agent_address",
    "source_url",
]

OFFICER_COLUMNS = [
    "company_number", "company_name", "officer_name",
    "officer_position", "start_date", "end_date", "inactive",
]

_STRIP_RE = re.compile(r"[^\w\s]")
_SPACE_RE = re.compile(r"\s+")
_SUFFIXES = {
    "INC", "LLC", "LLP", "CORP", "CO", "LTD", "LP", "PC",
    "PLLC", "DBA", "THE", "AND", "OF", "SA", "SRL",
    "HOSPITAL", "HEALTH", "CENTER", "CENTRE",
}


def _normalize(name: str) -> str:
    if not name or pd.isna(name):
        return ""
    n = str(name).upper()
    n = _STRIP_RE.sub(" ", n)
    n = _SPACE_RE.sub(" ", n).strip()
    tokens = n.split()
    while tokens and tokens[-1] in _SUFFIXES:
        tokens.pop()
    return " ".join(tokens)


def _session(api_token: str | None) -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": "ContractSweeper/1.0 (PR corporate registry research)",
        "Accept":     "application/json",
    })
    if api_token:
        s.headers["Authorization"] = f"Token {api_token}"
    return s


def _get(session: requests.Session, url: str, params: dict, logger) -> dict | None:
    for attempt in range(MAX_RETRIES):
        try:
            resp = session.get(url, params=params, timeout=60)
            if resp.status_code == 429:
                logger.warning("  Rate limited — sleeping 90s")
                time.sleep(90)
                continue
            if resp.status_code == 401:
                logger.warning("  OpenCorporates: 401 unauthorized — using unauthenticated rate limit")
                time.sleep(2)
                return None
            if 400 <= resp.status_code < 500:
                logger.warning(f"  HTTP {resp.status_code}: {url}")
                return None
            resp.raise_for_status()
            time.sleep(PAGE_SLEEP)
            return resp.json()
        except requests.RequestException as exc:
            if attempt < MAX_RETRIES - 1:
                wait = RETRY_BACKOFF[attempt]
                logger.warning(f"  Attempt {attempt+1} failed ({exc}) — retrying in {wait}s")
                time.sleep(wait)
            else:
                logger.error(f"  All {MAX_RETRIES} attempts failed: {exc}")
    return None


def _fetch_companies(session: requests.Session, logger) -> list[dict]:
    url       = f"{OC_BASE}/companies/search"
    all_items = []

    for page in range(1, MAX_PAGES + 1):
        params = {
            "jurisdiction_code": JURISDICTION,
            "per_page":          PER_PAGE,
            "page":              page,
        }
        data = _get(session, url, params, logger)
        if data is None:
            break

        results = data.get("results", {})
        companies_block = results.get("companies", {})
        items = companies_block.get("items", [])
        if not items:
            break

        all_items.extend(c["company"] for c in items if "company" in c)

        total = companies_block.get("total_count", 0)
        if page == 1:
            logger.info(f"  OpenCorporates PR companies: {total:,} total")

        total_pages = companies_block.get("total_pages", page)
        if page >= total_pages:
            break

        if page % 20 == 0:
            logger.info(f"    Page {page}/{total_pages} ({len(all_items):,} records)")

    return all_items


def _fetch_officers_for_company(session: requests.Session, company_number: str,
                                company_name: str, logger) -> list[dict]:
    url    = f"{OC_BASE}/companies/{JURISDICTION}/{company_number}/officers"
    data   = _get(session, url, {"per_page": 100}, logger)
    if data is None:
        return []

    results  = data.get("results", {})
    officers = results.get("officers", {})
    items    = officers.get("items", []) if isinstance(officers, dict) else officers

    rows = []
    for item in items:
        o = item.get("officer", item)
        rows.append({
            "company_number":   company_number,
            "company_name":     company_name,
            "officer_name":     o.get("name", ""),
            "officer_position": o.get("position", ""),
            "start_date":       o.get("start_date", ""),
            "end_date":         o.get("end_date", ""),
            "inactive":         o.get("inactive", False),
        })
    return rows


def _companies_to_df(items: list[dict]) -> pd.DataFrame:
    if not items:
        return pd.DataFrame(columns=COMPANY_COLUMNS)

    rows = []
    for c in items:
        addr = c.get("registered_address") or {}
        agent = c.get("registered_agent") or {}
        rows.append({
            "company_number":   c.get("company_number", ""),
            "name":             c.get("name", ""),
            "jurisdiction_code": c.get("jurisdiction_code", JURISDICTION),
            "company_type":     c.get("company_type", ""),
            "incorporation_date": c.get("incorporation_date", ""),
            "dissolution_date": c.get("dissolution_date", ""),
            "current_status":   c.get("current_status", ""),
            "registered_address": addr.get("street_address", "") if isinstance(addr, dict) else str(addr),
            "agent_name":       agent.get("name", "") if isinstance(agent, dict) else str(agent),
            "agent_address":    agent.get("address", "") if isinstance(agent, dict) else "",
            "source_url":       c.get("opencorporates_url", ""),
        })

    df = pd.DataFrame(rows, columns=COMPANY_COLUMNS)
    return df


# ---------------------------------------------------------------------------

def run(root: Path = None, force: bool = False, api_token: str | None = None) -> dict:
    if root is None:
        root = PROJECT_ROOT
    if api_token is None:
        api_token = os.getenv("OPENCORPORATES_API_TOKEN")

    root    = Path(root)
    raw_dir = root / "data" / "staging" / "raw" / "opencorporates"
    raw_dir.mkdir(parents=True, exist_ok=True)
    out_dir = root / "data" / "staging" / "processed"
    out_dir.mkdir(parents=True, exist_ok=True)

    raw_path      = raw_dir / "pr_companies_raw.csv"
    companies_path = out_dir / "pr_opencorporates_companies.csv"
    officers_path  = out_dir / "pr_opencorporates_officers.csv"
    awards_path    = out_dir / "pr_all_awards_master.csv"

    logger  = setup_logging("download_opencorporates")
    session = _session(api_token)

    if api_token:
        logger.info("  OpenCorporates: authenticated (higher rate limit)")
    else:
        logger.info("  OpenCorporates: unauthenticated — rate limit applies")

    # ------------------------------------------------------------------
    # Fetch / load company list
    # ------------------------------------------------------------------
    if not force and raw_path.exists():
        logger.info(f"  Cached — loading {raw_path.name}")
        items = pd.read_csv(raw_path, dtype=str, low_memory=False).to_dict("records")
        logger.info(f"  {len(items):,} cached companies")
    else:
        logger.info("  Fetching PR companies from OpenCorporates...")
        items = _fetch_companies(session, logger)
        if items:
            pd.DataFrame(items).to_csv(raw_path, index=False, encoding="utf-8")
            logger.info(f"  {len(items):,} companies cached → {raw_path.name}")
        else:
            logger.warning("  No companies returned — API may be rate-limited or unavailable")

    df_companies = _companies_to_df(items)
    df_companies.to_csv(companies_path, index=False, encoding="utf-8")
    logger.info(f"  Written: {companies_path.name} ({len(df_companies):,} companies)")

    # ------------------------------------------------------------------
    # Fetch officers for companies that match awards master
    # ------------------------------------------------------------------
    officer_rows: list[dict] = []

    if awards_path.exists() and not df_companies.empty:
        logger.info("  Crossreffing against awards master for officer lookup...")
        awards = pd.read_csv(awards_path, dtype=str, low_memory=False)
        award_norms = set(
            _normalize(n) for n in awards["recipient_name"].dropna().unique()
        )

        matched_companies = df_companies[
            df_companies["name"].apply(_normalize).isin(award_norms)
        ]
        logger.info(f"  {len(matched_companies):,} companies match awards master — fetching officers...")

        for _, row in matched_companies.head(500).iterrows():
            num  = str(row.get("company_number", "")).strip()
            name = str(row.get("name", "")).strip()
            if not num:
                continue
            officers = _fetch_officers_for_company(session, num, name, logger)
            officer_rows.extend(officers)
            time.sleep(0.3)

    session.close()

    df_officers = pd.DataFrame(officer_rows, columns=OFFICER_COLUMNS) if officer_rows \
                  else pd.DataFrame(columns=OFFICER_COLUMNS)
    df_officers.to_csv(officers_path, index=False, encoding="utf-8")
    logger.info(f"  Written: {officers_path.name} ({len(df_officers):,} officer records)")

    active_ct = int((df_companies["current_status"].str.upper() == "ACTIVE").sum()) \
                if not df_companies.empty else 0

    logger.info("=" * 60)
    logger.info("OPENCORPORATES SUMMARY")
    logger.info("=" * 60)
    logger.info(f"  Total PR companies:    {len(df_companies):,}")
    logger.info(f"  Active:                {active_ct:,}")
    logger.info(f"  Officer records:       {len(df_officers):,}")

    return {
        "company_rows": len(df_companies),
        "officer_rows": len(df_officers),
        "status":       "OK" if len(df_companies) > 0 else "EMPTY",
        "companies_path": str(companies_path),
        "officers_path":  str(officers_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Download PR business entities from OpenCorporates"
    )
    parser.add_argument("--force",     action="store_true", help="Re-download even if cached")
    parser.add_argument("--api-token", dest="api_token", default=None,
                        help="OpenCorporates API token (default: OPENCORPORATES_API_TOKEN env var)")
    args = parser.parse_args()
    result = run(force=args.force, api_token=args.api_token)
    print(f"\nOpenCorporates complete: {result['company_rows']:,} companies, "
          f"{result['officer_rows']:,} officer records.")
    return 0 if result["status"] in ("OK", "EMPTY") else 1


if __name__ == "__main__":
    sys.exit(main())
