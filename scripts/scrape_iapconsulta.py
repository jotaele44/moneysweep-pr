"""
Scrape PR Oficina del Contralor (OCPR) audit & investigation reports from the
live iapconsulta.ocpr.gov.pr public search database.

iapconsulta is the OCPR's searchable database of audit reports and
investigation reports on PR government entities (agencies, municipalities,
public corporations, universities) — never individuals or private
businesses. Its "Tipo de Informe" filter has three values: Regular, Especial,
and Investigaciones, all three of which map onto the existing
``audit_type`` column in ``scripts.ingest_contralor.CONTRALOR_COLUMNS`` — this
is the same ``oficina_contralor`` source, not a separate dataset.

The search page (Informes.aspx) is classic ASP.NET WebForms, but the actual
results grid is populated client-side by jQuery DataTables against a plain
JSON handler that needs no session/viewstate/auth:

    POST https://iapconsulta.ocpr.gov.pr/app/server/code/handler/InformesPublicos.ashx
    Content-Type: application/x-www-form-urlencoded
    body: draw=<n>&start=<offset>&length=<n>&rama=&entidad=&numero=&tipo=&desde=&hasta=

The server ignores ``length`` and always returns a fixed page (observed as 10
rows), so pagination walks ``start`` forward by the *actual* number of rows
each response carried (not an assumed constant) until it reaches
``recordsTotal`` — which is re-read from every response, since the result set
is live and can grow while a multi-minute scrape is in flight. Each row's
``Open`` field embeds an ``<a href="../../OpenDoc.aspx?...">`` link to the
actual PDF report; ``report_url`` is extracted from that.

Output:
  data/staging/processed/pr_contralor_audits.csv (same schema/output path as
  scripts/ingest_contralor.py — this replaces it as the registered producer
  for the ``oficina_contralor`` source; ingest_contralor.py remains available
  as a manual-dropzone fallback).

Usage:
  python3 scripts/scrape_iapconsulta.py
  python3 scripts/scrape_iapconsulta.py --force
  python3 scripts/scrape_iapconsulta.py --max-pages 5   # smoke test
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path
from urllib.parse import urljoin

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import requests

from moneysweep.runtime.base_downloader import HttpConfig, build_session, file_has_data
from moneysweep.runtime.pagination_runtime import PageResult, paginate
from moneysweep.runtime.retry_runtime import RetryExhausted, RetryPolicy, with_retry
from scripts.config import PROJECT_ROOT, setup_logging
from scripts.ingest_contralor import CONTRALOR_COLUMNS, _normalize_name

BASE_URL = "https://iapconsulta.ocpr.gov.pr/"
SEARCH_URL = BASE_URL + "app/server/code/handler/InformesPublicos.ashx"
OUT_PATH_REL = "data/staging/processed/pr_contralor_audits.csv"

PAGE_SIZE = 10  # server-enforced first-page hint only; actual advance uses len(batch)

HTTP = HttpConfig(
    user_agent="Mozilla/5.0 (compatible; ContractSweeper/1.0; PR audit research)",
    extra_headers={"X-Requested-With": "XMLHttpRequest", "Referer": BASE_URL},
    max_retries=3,
    base_delay_seconds=5.0,
    max_delay_seconds=30.0,
    page_sleep=0.5,
    rate_limit_sleep=60.0,
    timeout=30,
)
RETRY_POLICY = RetryPolicy(
    max_attempts=HTTP.max_retries,
    base_delay_seconds=HTTP.base_delay_seconds,
    max_delay_seconds=HTTP.max_delay_seconds,
)

_HREF_RE = re.compile(r'href="([^"]+)"')
_YEAR_RE = re.compile(r"(\d{4})")


class _RateLimited(Exception):
    """Internal marker so a 429 is retried by with_retry (mirrors base_downloader)."""


def _session() -> requests.Session:
    return build_session(HTTP.user_agent, HTTP.extra_headers)


def _fetch_page(session: requests.Session, start: int, logger) -> dict | None:
    """POST one page. Returns the parsed JSON, or None on a terminal 4xx / retry
    exhaustion — same contract as base_downloader.http_post_json, which this
    can't call directly because the endpoint needs form-urlencoded POST data,
    not a JSON body."""
    payload = {
        "draw": 1,
        "start": start,
        "length": PAGE_SIZE,
        "rama": "",
        "entidad": "",
        "numero": "",
        "tipo": "",
        "desde": "",
        "hasta": "",
    }

    def _once() -> dict | None:
        resp = session.post(
            SEARCH_URL,
            data=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded; charset=utf-8"},
            timeout=HTTP.timeout,
        )
        if resp.status_code == 429:
            logger.warning(f"  Rate limited at start={start} — sleeping {HTTP.rate_limit_sleep}s")
            time.sleep(HTTP.rate_limit_sleep)
            raise _RateLimited()
        if 400 <= resp.status_code < 500:
            logger.error(f"  HTTP {resp.status_code} at start={start}: {resp.text[:200]}")
            return None
        resp.raise_for_status()
        time.sleep(HTTP.page_sleep)
        return resp.json()

    try:
        return with_retry(
            _once, policy=RETRY_POLICY, retry_on=(requests.RequestException, _RateLimited)
        )
    except RetryExhausted as exc:
        logger.error(f"  Page start={start} failed: {exc}")
        return None


def _extract_report_url(open_html: str | None) -> str:
    if not open_html:
        return ""
    m = _HREF_RE.search(open_html)
    if not m:
        return ""
    return urljoin(BASE_URL, m.group(1))


def _year_from_date(value: str | None) -> str:
    m = _YEAR_RE.search(value or "")
    return m.group(1) if m else ""


def _normalize_row(record: dict) -> dict:
    entidad = (record.get("Entidad") or "").strip()
    if entidad in ("", "N/A"):
        entidad = (record.get("NombreInforme") or "").strip()
    audit_date = (record.get("Publicacion") or "").strip()

    row = {col: "" for col in CONTRALOR_COLUMNS}
    row.update(
        {
            "entity_name": entidad,
            "entity_normalized": _normalize_name(entidad),
            "audit_id": (record.get("NumInforme") or "").strip(),
            "audit_type": (record.get("TipoInforme") or "").strip(),
            "audit_year": _year_from_date(audit_date),
            "audit_date": audit_date,
            "branch": (record.get("Rama") or "").strip(),
            "report_url": _extract_report_url(record.get("Open")),
            "source_file": "iapconsulta.ocpr.gov.pr",
        }
    )
    return row


def fetch_all_records(
    session: requests.Session, logger, max_pages: int | None = None
) -> tuple[list[dict], bool]:
    """Page through the search API. Returns (records, truncated) — `truncated`
    is True iff a page fetch failed mid-scrape (as opposed to a clean stop at
    `recordsTotal` or an intentional `max_pages` cutoff), so callers can tell
    a partial result apart from a complete one instead of treating both as a
    normal `rows > 0` success."""
    total_known = False
    truncated = False

    def _fetch(start: int) -> PageResult:
        nonlocal total_known, truncated
        page_num = start // PAGE_SIZE + 1
        data = _fetch_page(session, start, logger)
        if data is None:
            truncated = True
            return PageResult(records=[], next_marker=None)

        total = data.get("recordsTotal") or 0
        if not total_known:
            logger.info(f"  recordsTotal={total:,}")
            total_known = True

        batch = data.get("data") or []
        next_start = start + len(batch)
        if page_num % 20 == 0:
            logger.info(f"    page {page_num}: {next_start:,}/{total:,} records so far")
        next_marker = next_start if batch and next_start < total else None
        return PageResult(records=batch, next_marker=next_marker)

    records = list(paginate(_fetch, start_marker=0, max_pages=max_pages))
    return records, truncated


def run(root=None, max_pages=None):
    return _run(root=root, force=False, max_pages=max_pages)


def _run(root=None, force=False, max_pages=None):
    if root is None:
        root = PROJECT_ROOT
    out_path = Path(root) / OUT_PATH_REL
    logger = setup_logging("scrape_iapconsulta")
    logger.info("Starting iapconsulta.ocpr.gov.pr audit/investigation scrape...")

    if not force and file_has_data(out_path):
        existing = pd.read_csv(out_path, dtype=str, low_memory=False)
        logger.info(f"  {out_path.name} exists ({len(existing):,} rows) — skipping.")
        return {"rows": len(existing), "path": str(out_path), "errors": []}

    session = _session()
    raw_records, truncated = fetch_all_records(session, logger, max_pages=max_pages)
    session.close()

    if not raw_records:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(columns=CONTRALOR_COLUMNS).to_csv(out_path, index=False, encoding="utf-8")
        return {"rows": 0, "path": str(out_path), "errors": ["No records fetched from iapconsulta"]}

    rows = [_normalize_row(r) for r in raw_records]
    combined = pd.DataFrame(rows, columns=CONTRALOR_COLUMNS)
    combined = combined[combined["entity_name"] != ""].drop_duplicates()

    out_path.parent.mkdir(parents=True, exist_ok=True)
    combined.to_csv(out_path, index=False, encoding="utf-8")

    errors = []
    if truncated:
        msg = (
            f"Scrape stopped early after a page fetch failure — only "
            f"{len(combined):,} records captured; re-run with --force once the "
            f"endpoint recovers"
        )
        logger.error(f"  {msg}")
        errors.append(msg)

    by_type = combined["audit_type"].value_counts().to_dict()
    logger.info("=" * 60)
    logger.info("IAPCONSULTA SCRAPE SUMMARY")
    logger.info("=" * 60)
    logger.info(f"  Total records:   {len(combined):,}")
    logger.info(f"  Unique entities: {combined['entity_normalized'].nunique():,}")
    logger.info(f"  By report type:  {by_type}")

    return {"rows": len(combined), "path": str(out_path), "errors": errors}


def main():
    parser = argparse.ArgumentParser(
        description="Scrape PR OCPR audit/investigation reports from iapconsulta"
    )
    parser.add_argument("--force", action="store_true")
    parser.add_argument(
        "--max-pages", type=int, default=None, help="Limit pages fetched (smoke testing)"
    )
    args = parser.parse_args()
    result = _run(force=args.force, max_pages=args.max_pages)
    print(f"\niapconsulta scrape complete: {result['rows']:,} audit/investigation records")
    return 1 if result["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
