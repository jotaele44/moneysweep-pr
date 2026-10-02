"""
Scrape ASG emergency (no-bid) purchase orders from asg.pr.gov/comprasemergencias.

The Administración de Servicios Generales is Puerto Rico's central procurement
authority (Ley 73-2019). Under an declared emergency it may buy without going to
bid, and it publishes those purchases as a plain server-rendered HTML table —
the only page on the ASG site that carries dollar amounts in its markup:

    Número de Control ASG | Número Orden de Compra | Bienes o servicios a
    adquirir | Proveedor | Costo | Agencia

Historically ~1,400 rows over 141 pages; live verification on 2026-10-01 shows
144 declared pages. The exact refreshed row denominator remains open until a
full pull completes. Control numbers encode emergency programmes as
``<FY>-ASG-<PROGRAMME>-<SEQ>``. Examples include:

    20-ASG-CV19-765   COVID-19
    22-ASG-TTF-296    Tormenta Tropical Fiona
    26-ASG-EPI-0010   epidemiological emergency
    26-ASG-AAA-0033   current 2026 AAA-labelled programme (label unresolved here)

This is deliberately NOT covered by the ``ocpr_contracts`` source. That registry
is the Comptroller's record of executed *contracts*; emergency purchase orders
largely bypass it, which is exactly why they are worth holding separately.

Two things about the endpoint shape the scraper:

* Paging is a plain query param (``?page=N&order_by=-creado``), but requesting a
  page past the end **clamps to the last page** instead of returning an empty
  one — a request past the end serves the last page again. A
  walk-until-empty loop would never terminate, so the page count is read from
  the "Página 1 de N" marker, with a repeated-page check as a backstop in case
  that marker ever moves.
* No date column is rendered — and there is no other way to get one. There is no
  JSON API (``/api/comprasemergencias``, ``.json`` and ``?format=json`` all fail),
  the rows carry no links so there are no detail pages, and the six sortable
  columns are control number, PO number, goods, vendor, cost and agency.
  ``order_by=creado`` *does* re-sort the table, which proves the server holds a
  creation timestamp — it simply never renders it.

  So ``fiscal_year`` is derived from the control-number prefix and **no
  ``transaction_date`` is claimed**. Two honest observations stand in for it:

    creado_rank    the row's position in the ``-creado`` ordering at capture
                   time. Monotonic in creation time, so rows can be sequenced
                   and new arrivals spotted between polls. It is a rank within
                   one pull, not a stable key — inserting a newer purchase
                   shifts every rank below it.
    first_seen_at  the UTC date this control number first appeared in our own
                   output, carried forward from the existing CSV on each run.
                   A true upper bound on the purchase date that tightens as
                   history accumulates.

Output:
  data/staging/processed/pr_asg_emergency_purchases.csv

Usage:
  python3 scripts/scrape_asg_emergency_purchases.py
  python3 scripts/scrape_asg_emergency_purchases.py --force
  python3 scripts/scrape_asg_emergency_purchases.py --max-pages 3   # smoke test
"""

from __future__ import annotations

import argparse
import io
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import requests

from moneysweep.runtime.base_downloader import HttpConfig, build_session, file_has_data
from moneysweep.runtime.post_ingest import apply_post_ingest
from moneysweep.runtime.retry_runtime import RetryExhausted, RetryPolicy, with_retry
from scripts.config import PROJECT_ROOT, setup_logging

SOURCE_ID = "asg_emergency_purchases"
BASE_URL = "https://asg.pr.gov/comprasemergencias"
OUT_PATH_REL = "data/staging/processed/pr_asg_emergency_purchases.csv"

HTTP = HttpConfig(
    user_agent="Mozilla/5.0 (compatible; MoneySweep/1.0; PR public-money research)",
    max_retries=3,
    base_delay_seconds=5.0,
    max_delay_seconds=30.0,
    page_sleep=0.3,
    rate_limit_sleep=60.0,
    timeout=30,
)
RETRY_POLICY = RetryPolicy(
    max_attempts=HTTP.max_retries,
    base_delay_seconds=HTTP.base_delay_seconds,
    max_delay_seconds=HTTP.max_delay_seconds,
)

EMERGENCY_PURCHASE_COLUMNS = [
    "control_number",
    "contract_number",
    "description",
    "vendor_source_label",
    "vendor_name",
    "vendor_registration_id",
    "vendor_identity_scheme",
    "vendor_identity_state",
    "obligation_amount",
    "awarding_agency",
    "fiscal_year",
    "emergency_programme_code",
    "emergency_programme",
    # ASG renders no date. These two are OBSERVATIONS, not the purchase date —
    # see the module docstring. Neither may be promoted to transaction_date.
    "creado_rank",
    "first_seen_at",
    "source_system",
    "source_url",
    "source_file",
]

# Spanish column headings, mapped to the canonical names in
# registries/schema_registry.yaml. `vendor_name` and `obligation_amount` are
# named to match post_ingest's ENTITY_NAME_COLUMNS / AMOUNT_COLUMNS so the
# enrichment pass picks them up without a per-source special case.
COL_MAP = {
    "Número de Control ASG": "control_number",
    "Número Orden de Compra": "contract_number",
    "Bienes o servicios a adquirir": "description",
    "Proveedor": "vendor_name",
    "Costo": "obligation_amount",
    "Agencia": "awarding_agency",
}

# Declared emergencies seen in the control numbers. Unknown codes pass through
# with an empty label rather than being dropped — a new emergency must still
# ingest, it just will not have a name yet.
EMERGENCY_PROGRAMMES = {
    "CV19": "COVID-19",
    "TTF": "Tormenta Tropical Fiona",
    "EPI": "Emergencia epidemiológica",
}

# 26-ASG-EPI-0010 -> ("26", "EPI"). The middle token is always "ASG".
_CONTROL_RE = re.compile(r"^\s*(\d{2})-ASG-([A-Z0-9]+)-", re.I)
_PAGE_COUNT_RE = re.compile(r"P[áa]gina\s*\d+\s*de\s*(\d+)", re.I)
_VENDOR_ID_RE = re.compile(r"^(.*?)\s*\((\d+)\)\s*$")


class _RateLimited(Exception):
    """Internal marker so a 429 is retried by with_retry (mirrors base_downloader)."""


def _page_url(page: int) -> str:
    return f"{BASE_URL}?page={page}&order_by=-creado"


def declared_page_count(html: str) -> int | None:
    """Total pages from the live "Página 1 de N" marker, or None if absent."""
    match = _PAGE_COUNT_RE.search(html)
    return int(match.group(1)) if match else None


def fiscal_year_and_programme(control_number: str) -> tuple[str, str, str]:
    """(fiscal_year, programme_code, programme_label) from an ASG control number.

    The control number is the only place a row says when it happened — the table
    renders no date column at all.
    """
    match = _CONTROL_RE.match(control_number or "")
    if not match:
        return "", "", ""
    year, code = match.group(1), match.group(2).upper()
    return f"20{year}", code, EMERGENCY_PROGRAMMES.get(code, "")


def _clean(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return " ".join(str(value).split())


def split_vendor_identity(value: object) -> tuple[str, str, str, str]:
    """Return source label, display name, registration ID and identity state.

    Only an explicit trailing numeric ASG token in the Proveedor cell is
    promoted to identity. Legacy name-only rows remain unresolved.
    """
    source_label = _clean(value)
    if not source_label:
        return "", "", "", "UNRESOLVED_MISSING_VENDOR"
    match = _VENDOR_ID_RE.match(source_label)
    if not match:
        return source_label, source_label, "", "UNRESOLVED_NAME_ONLY"
    name = _clean(match.group(1))
    registration_id = match.group(2)
    return source_label, name, registration_id, "SOURCE_NATIVE_ASG_LICITADOR_ID"


def _normalize_row(record: dict, creado_rank: int | None = None) -> dict:
    """One raw table row (keyed by its Spanish heading) to a canonical row.

    ``creado_rank`` is the row's 1-based position in the ``-creado`` ordering.
    """
    control_number = _clean(record.get("Número de Control ASG"))
    fiscal_year, code, programme = fiscal_year_and_programme(control_number)

    row = {col: "" for col in EMERGENCY_PURCHASE_COLUMNS}
    for heading, canonical in COL_MAP.items():
        row[canonical] = _clean(record.get(heading))
    source_label, vendor_name, registration_id, identity_state = split_vendor_identity(
        record.get("Proveedor")
    )
    row["vendor_source_label"] = source_label
    row["vendor_name"] = vendor_name
    row["vendor_registration_id"] = registration_id
    row["vendor_identity_scheme"] = "asg_licitador_id" if registration_id else ""
    row["vendor_identity_state"] = identity_state
    row.update(
        {
            "fiscal_year": fiscal_year,
            "emergency_programme_code": code,
            "emergency_programme": programme,
            "creado_rank": "" if creado_rank is None else str(creado_rank),
            "source_system": SOURCE_ID,
            "source_url": BASE_URL,
            "source_file": "asg.pr.gov/comprasemergencias",
        }
    )
    return row


def _carry_forward_first_seen(frame: pd.DataFrame, out_path: Path, today: str) -> pd.DataFrame:
    """Preserve each control number's existing ``first_seen_at``, stamping new ones.

    The value is only meaningful if it never moves: re-stamping every row each
    run would turn an upper bound on the purchase date into "the date we last
    scraped", which is worse than leaving it blank. So prior values win and only
    genuinely new control numbers get today's date.
    """
    previous: dict[str, str] = {}
    if out_path.exists():
        try:
            existing = pd.read_csv(out_path, dtype=str, low_memory=False)
        except (OSError, pd.errors.ParserError, pd.errors.EmptyDataError):
            existing = None
        if existing is not None and {"control_number", "first_seen_at"} <= set(existing.columns):
            previous = {
                str(c): str(f)
                for c, f in zip(existing["control_number"], existing["first_seen_at"])
                if isinstance(f, str) and f.strip()
            }

    frame = frame.copy()
    frame["first_seen_at"] = [previous.get(str(c), today) for c in frame["control_number"]]
    return frame


def parse_records(html: str) -> list[dict]:
    """Rows of the purchases table, keyed by their Spanish headings.

    Uses pandas.read_html rather than adding a parser dependency; the page is a
    single well-formed table with a real <thead>. The trailing "↩" reset-sort
    column carries no data and is dropped by COL_MAP.

    ``flavor`` is pinned to lxml deliberately: left to choose, pandas falls back
    to html5lib when it finds no table, and html5lib is not a dependency here —
    so an ASG error page (which still answers 200) would raise ImportError
    instead of parsing to nothing.
    """
    try:
        tables = pd.read_html(io.StringIO(html), flavor="lxml")
    except ValueError:  # "No tables found" — an error page or an empty result
        return []
    if not tables:
        return []

    frame = tables[0]
    if "Número de Control ASG" not in frame.columns:
        return []
    records = frame.to_dict(orient="records")
    return [r for r in records if _clean(r.get("Número de Control ASG"))]


def _fetch_page(session: requests.Session, page: int, logger) -> str | None:
    """GET one listing page. None on a terminal 4xx or retry exhaustion."""

    def _once() -> str | None:
        resp = session.get(_page_url(page), timeout=HTTP.timeout)
        if resp.status_code == 429:
            logger.warning(f"  Rate limited on page {page} — sleeping {HTTP.rate_limit_sleep}s")
            time.sleep(HTTP.rate_limit_sleep)
            raise _RateLimited()
        if 400 <= resp.status_code < 500:
            logger.error(f"  HTTP {resp.status_code} on page {page}")
            return None
        resp.raise_for_status()
        time.sleep(HTTP.page_sleep)
        return resp.text

    try:
        return with_retry(
            _once, policy=RETRY_POLICY, retry_on=(requests.RequestException, _RateLimited)
        )
    except RetryExhausted as exc:
        logger.error(f"  Page {page} failed: {exc}")
        return None


def fetch_all_records(
    session: requests.Session, logger, max_pages: int | None = None
) -> tuple[list[dict], bool]:
    """Walk every page. Returns (records, truncated).

    ``truncated`` is True iff a page fetch failed mid-scrape, so a partial
    result can be told apart from a clean finish — the same contract as
    scrape_iapconsulta.fetch_all_records.
    """
    records: list[dict] = []
    truncated = False
    total_pages: int | None = None
    previous_signature: tuple[str, ...] | None = None
    page = 1

    while True:
        if max_pages is not None and page > max_pages:
            break
        if total_pages is not None and page > total_pages:
            break

        html = _fetch_page(session, page, logger)
        if html is None:
            truncated = True
            break

        if total_pages is None:
            total_pages = declared_page_count(html)
            logger.info(f"  declared pages: {total_pages if total_pages else 'unknown'}")

        batch = parse_records(html)
        if not batch:
            break

        # Requesting a page past the end serves the LAST page again rather than
        # an empty one, so an unchanged batch means the walk is over. Without
        # this the loop cannot terminate whenever the page marker is missing.
        signature = tuple(_clean(r.get("Número de Control ASG")) for r in batch)
        if signature == previous_signature:
            logger.info(f"  page {page} repeated page {page - 1} — stopping")
            break
        previous_signature = signature

        records.extend(batch)
        if page % 20 == 0:
            logger.info(f"    page {page}: {len(records):,} records so far")
        page += 1

    return records, truncated


def run(root=None, force: bool = False, max_pages: int | None = None) -> dict:
    return _run(root=root, force=force, max_pages=max_pages)


def _run(root=None, force: bool = False, max_pages: int | None = None) -> dict:
    if root is None:
        root = PROJECT_ROOT
    out_path = Path(root) / OUT_PATH_REL
    logger = setup_logging("scrape_asg_emergency_purchases")
    logger.info("Starting ASG emergency-purchase scrape...")

    if not force and file_has_data(out_path):
        existing = pd.read_csv(out_path, dtype=str, low_memory=False)
        logger.info(f"  {out_path.name} exists ({len(existing):,} rows) — skipping.")
        return {"status": "OK", "rows": len(existing), "path": str(out_path), "errors": []}

    session = build_session(HTTP.user_agent, HTTP.extra_headers)
    try:
        raw_records, truncated = fetch_all_records(session, logger, max_pages=max_pages)
    finally:
        session.close()

    out_path.parent.mkdir(parents=True, exist_ok=True)

    if not raw_records:
        pd.DataFrame(columns=EMERGENCY_PURCHASE_COLUMNS).to_csv(
            out_path, index=False, encoding="utf-8"
        )
        return {
            "status": "ERROR",
            "rows": 0,
            "path": str(out_path),
            "errors": ["No records fetched from asg.pr.gov/comprasemergencias"],
        }

    # Records arrive in -creado order, so enumeration position IS the rank.
    frame = pd.DataFrame(
        [_normalize_row(r, creado_rank=i) for i, r in enumerate(raw_records, start=1)],
        columns=EMERGENCY_PURCHASE_COLUMNS,
    )
    frame = frame.drop_duplicates(subset=["control_number"])
    # Read before the file is overwritten, so prior first_seen_at values survive.
    frame = _carry_forward_first_seen(
        frame, out_path, datetime.now(timezone.utc).date().isoformat()
    )
    # Adds obligation_amount_canonical, entity_normalized and the geo columns.
    frame = apply_post_ingest(frame, source_id=SOURCE_ID, root=Path(root))
    frame.to_csv(out_path, index=False, encoding="utf-8")

    errors = []
    if truncated:
        msg = (
            f"Scrape stopped early after a page fetch failure — only "
            f"{len(frame):,} records captured; re-run with --force once the "
            f"endpoint recovers"
        )
        logger.error(f"  {msg}")
        errors.append(msg)

    logger.info("=" * 60)
    logger.info("ASG EMERGENCY PURCHASE SCRAPE SUMMARY")
    logger.info("=" * 60)
    logger.info(f"  Total records:  {len(frame):,}")
    logger.info(f"  By emergency:   {frame['emergency_programme_code'].value_counts().to_dict()}")
    logger.info(f"  Unique vendors: {frame['vendor_name'].nunique():,}")
    logger.info(
        "  Source-native vendor IDs: "
        f"{(frame['vendor_registration_id'].astype(str).str.strip() != '').sum():,}"
    )
    if "obligation_amount_canonical" in frame.columns:
        logger.info(f"  Total value:    ${frame['obligation_amount_canonical'].sum():,.2f}")

    return {
        "status": "TRUNCATED" if truncated else "OK",
        "rows": len(frame),
        "path": str(out_path),
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Scrape ASG emergency (no-bid) purchase orders")
    parser.add_argument("--force", action="store_true")
    parser.add_argument(
        "--max-pages", type=int, default=None, help="Limit pages fetched (smoke testing)"
    )
    args = parser.parse_args()
    result = _run(force=args.force, max_pages=args.max_pages)
    print(f"\nASG emergency-purchase scrape complete: {result['rows']:,} purchase orders")
    return 1 if result["errors"] and result["rows"] == 0 else 0


if __name__ == "__main__":
    sys.exit(main())
