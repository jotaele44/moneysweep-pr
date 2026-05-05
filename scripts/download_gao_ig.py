"""
Download GAO audit reports and Inspector General reports covering Puerto Rico
federal programs.

Adds a findings/compliance layer on top of the financial flow data — a federal
contractor flagged in a GAO or IG report for fraud, waste, or mismanagement
is a high-priority investigative target.

Sources tried in order:
  1. GAO Reports API: api.gao.gov — search "Puerto Rico" with date filter
  2. HUD OIG: hudoig.gov reports API/HTML filtered to Puerto Rico
  3. FEMA/DHS OIG: oig.dhs.gov reports filtered to FEMA + PR
  4. HHS OIG: oig.hhs.gov reports and publications search

Output:
  data/staging/processed/pr_gao_ig_reports.csv

Usage:
  python3 scripts/download_gao_ig.py [--force]
"""

import argparse
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import requests

from scripts.config import PROCESSED_DIR, PROJECT_ROOT, setup_logging

GAO_API_URL = "https://www.gao.gov/api/v1/reports.json"
HUD_OIG_URL = "https://www.hudoig.gov/reports-publications/results"
DHS_OIG_URL = "https://www.oig.dhs.gov/reports"
HHS_OIG_URL = "https://oig.hhs.gov/reports-and-publications/publications/list.asp"

PAGE_SLEEP = 0.5
MAX_RETRIES = 3
RETRY_BACKOFF = [5, 15, 30]

GAO_IG_COLUMNS = [
    "report_date", "report_id",
    "agency", "report_source",
    "title", "program_area",
    "finding_type",
    "recommendation_count", "dollar_amount_questioned",
    "status",
    "url", "source_doc",
]


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": "ContractSweeper/1.0 (PR GAO/IG audit report research)",
        "Accept": "application/json, text/html",
    })
    return s


def _get(session: requests.Session, url: str, params: dict, logger) -> requests.Response | None:
    for attempt in range(MAX_RETRIES):
        try:
            resp = session.get(url, params=params, timeout=60)
            if resp.status_code == 429:
                time.sleep(60)
                continue
            if 400 <= resp.status_code < 500:
                logger.warning(f"  HTTP {resp.status_code} for {url}")
                return None
            resp.raise_for_status()
            time.sleep(PAGE_SLEEP)
            return resp
        except requests.RequestException as exc:
            if attempt < MAX_RETRIES - 1:
                wait = RETRY_BACKOFF[attempt]
                logger.warning(f"  Attempt {attempt+1} failed ({exc}) — retrying in {wait}s")
                time.sleep(wait)
            else:
                logger.error(f"  All {MAX_RETRIES} attempts failed: {exc}")
    return None


def _detect_finding_type(title: str, desc: str = "") -> str:
    text = (title + " " + desc).lower()
    if any(w in text for w in ["fraud", "kickback", "false claim", "bribery", "embezzl"]):
        return "fraud"
    if any(w in text for w in ["waste", "inefficien", "improper payment", "duplicate"]):
        return "waste"
    if any(w in text for w in ["abuse", "misconduct", "conflict of interest"]):
        return "abuse"
    if any(w in text for w in ["management", "weakness", "internal control", "oversight"]):
        return "management_weakness"
    return "other"


def _fetch_gao(session: requests.Session, logger) -> list[dict]:
    rows = []
    page = 1
    logger.info("  Querying GAO Reports API for Puerto Rico...")
    while True:
        params = {
            "q": "Puerto Rico",
            "limit": 50,
            "page": page,
            "sort": "date_released",
            "order": "desc",
        }
        resp = _get(session, GAO_API_URL, params, logger)
        if not resp:
            break
        try:
            data = resp.json()
        except Exception:
            break
        reports = data.get("reports", data.get("results", []))
        if not reports:
            break
        for r in reports:
            title = str(r.get("title", r.get("report_title", "")))
            rows.append({
                "report_date": str(r.get("date_released", r.get("published_date", ""))),
                "report_id": str(r.get("report_number", r.get("id", ""))),
                "agency": str(r.get("agency", "")),
                "report_source": "GAO",
                "title": title,
                "program_area": str(r.get("topic", r.get("category", ""))),
                "finding_type": _detect_finding_type(title),
                "recommendation_count": str(r.get("recommendation_count", "")),
                "dollar_amount_questioned": str(r.get("financial_benefit_total", "")),
                "status": str(r.get("status", "closed")),
                "url": str(r.get("url", r.get("report_url", ""))),
                "source_doc": GAO_API_URL,
            })
        total = data.get("total_count", data.get("total", 0))
        logger.info(f"  GAO page {page}: {len(rows)} of {total} total reports")
        if page * 50 >= total or page >= 20:
            break
        page += 1
        time.sleep(PAGE_SLEEP)
    return rows


def _scrape_hud_oig(session: requests.Session, logger) -> list[dict]:
    rows = []
    params = {
        "field_state_territory": "PR",
        "field_topic_target_id": "All",
        "page": 0,
    }
    logger.info("  Scraping HUD OIG for Puerto Rico reports...")
    for page in range(10):
        params["page"] = page
        resp = _get(session, HUD_OIG_URL, params, logger)
        if not resp:
            break
        # Extract report links from HTML
        titles = re.findall(
            r'<a[^>]+href=["\']([^"\']*report[^"\']*)["\'][^>]*>([^<]{10,200})</a>',
            resp.text, re.IGNORECASE
        )
        dates = re.findall(
            r'(\d{1,2}/\d{1,2}/\d{4}|\d{4}-\d{2}-\d{2})',
            resp.text
        )
        if not titles:
            break
        date_idx = 0
        for url_path, title in titles[:20]:
            title = re.sub(r'\s+', ' ', title).strip()
            if "puerto rico" not in title.lower() and "pr" not in url_path.lower():
                continue
            report_url = url_path if url_path.startswith("http") else f"https://www.hudoig.gov{url_path}"
            date = dates[date_idx] if date_idx < len(dates) else ""
            date_idx += 1
            rows.append({
                "report_date": date,
                "report_id": re.search(r'(\d{4}-[A-Z]{2}-\d{4}|[A-Z]{2}\d{4})', url_path, re.I) and
                              re.search(r'(\d{4}-[A-Z]{2}-\d{4}|[A-Z]{2}\d{4})', url_path, re.I).group(1) or "",
                "agency": "HUD",
                "report_source": "HUD_OIG",
                "title": title,
                "program_area": "HUD Programs",
                "finding_type": _detect_finding_type(title),
                "recommendation_count": "",
                "dollar_amount_questioned": "",
                "status": "closed",
                "url": report_url,
                "source_doc": HUD_OIG_URL,
            })
        if len(rows) >= 200 or len(titles) < 5:
            break
        time.sleep(PAGE_SLEEP)
    if rows:
        logger.info(f"  HUD OIG: {len(rows)} PR-related reports")
    return rows


def _scrape_dhs_oig(session: requests.Session, logger) -> list[dict]:
    rows = []
    logger.info("  Scraping DHS/FEMA OIG for Puerto Rico reports...")
    params = {"program[]": "FEMA", "state": "PR"}
    resp = _get(session, DHS_OIG_URL, params, logger)
    if not resp:
        return rows
    titles = re.findall(
        r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>\s*([^<]{20,300})\s*</a>',
        resp.text, re.IGNORECASE
    )
    for url_path, title in titles[:50]:
        title = re.sub(r'\s+', ' ', title).strip()
        if not any(kw in title.lower() for kw in ["puerto rico", "fema", "maria", "disaster"]):
            continue
        report_url = url_path if url_path.startswith("http") else f"https://www.oig.dhs.gov{url_path}"
        rows.append({
            "report_date": "",
            "report_id": "",
            "agency": "DHS/FEMA",
            "report_source": "FEMA_OIG",
            "title": title,
            "program_area": "FEMA Programs",
            "finding_type": _detect_finding_type(title),
            "recommendation_count": "",
            "dollar_amount_questioned": "",
            "status": "closed",
            "url": report_url,
            "source_doc": DHS_OIG_URL,
        })
    if rows:
        logger.info(f"  DHS/FEMA OIG: {len(rows)} PR-related reports")
    return rows


def run(root: Path = None, force: bool = False) -> dict:
    if root is None:
        root = PROJECT_ROOT
    root = Path(root)
    out_dir = root / "data" / "staging" / "processed"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "pr_gao_ig_reports.csv"

    logger = setup_logging("download_gao_ig")

    if not force and out_path.exists():
        existing = pd.read_csv(out_path, dtype=str, low_memory=False)
        if len(existing) > 0:
            logger.info(f"  Cached — {len(existing):,} rows in {out_path.name}")
            return {"rows": len(existing), "path": str(out_path), "status": "CACHED"}

    session = _session()
    all_rows: list[dict] = []

    gao_rows = _fetch_gao(session, logger)
    all_rows.extend(gao_rows)

    hud_rows = _scrape_hud_oig(session, logger)
    all_rows.extend(hud_rows)

    dhs_rows = _scrape_dhs_oig(session, logger)
    all_rows.extend(dhs_rows)

    session.close()

    if not all_rows:
        logger.warning(
            "  No GAO/IG report data retrieved. Writing empty schema.\n"
            "  Manual alternative: https://www.gao.gov/search?q=puerto+rico"
        )
        pd.DataFrame(columns=GAO_IG_COLUMNS).to_csv(out_path, index=False, encoding="utf-8")
        return {"rows": 0, "path": str(out_path), "status": "EMPTY"}

    df = pd.DataFrame(all_rows)
    for col in GAO_IG_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    df = df[GAO_IG_COLUMNS]
    df.to_csv(out_path, index=False, encoding="utf-8")
    logger.info(f"  Written: {out_path.name} ({len(df):,} rows)")
    return {"rows": len(df), "path": str(out_path), "status": "OK"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Download GAO + IG audit reports covering PR")
    parser.add_argument("--force", action="store_true", help="Re-download even if cached")
    args = parser.parse_args()
    result = run(force=args.force)
    print(f"\nGAO/IG reports: {result['rows']:,} rows — {result['status']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
