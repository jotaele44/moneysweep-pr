"""
Download Puerto Rico government procurement data from Compras PR
(comprashpr.com) — the official PR procurement portal for RFPs and awards.

This captures the state-level procurement layer that sits between federal
pass-through funding and contractor selection. Connecting these RFPs to LDA
lobbying filings quantifies lobby influence on procurement design timing.

Outputs:
  data/staging/raw/compras/compras_rfps_raw.json
  data/staging/raw/compras/compras_awards_raw.json
  data/staging/processed/pr_compras_rfps.csv
  data/staging/processed/pr_compras_awards.csv

Usage:
  python3 scripts/download_compras.py
  python3 scripts/download_compras.py --force
  python3 scripts/download_compras.py --max-pages 50
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import requests

from scripts.config import PROCESSED_DIR, PROJECT_ROOT, setup_logging
from scripts.build_unified_master import _normalize_name

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

COMPRAS_BASE = "https://www.comprashpr.com"

# Known Compras portal API patterns (XHR endpoints used by the site)
COMPRAS_ENDPOINTS = {
    "rfps":   [
        "/api/solicitations",
        "/api/solicitudes",
        "/api/rfp",
        "/busqueda/solicitudes",
    ],
    "awards": [
        "/api/awards",
        "/api/contratos",
        "/api/contract-awards",
        "/busqueda/contratos",
    ],
}

PAGE_SIZE    = 100
PAGE_SLEEP   = 0.5
MAX_RETRIES  = 3
RETRY_BACKOFF = [5, 15, 30]
DEFAULT_MAX_PAGES = 200

RFP_COLUMNS = [
    "rfp_id", "title", "agency", "agency_normalized",
    "posted_date", "due_date", "estimated_value", "status",
]

AWARD_COLUMNS = [
    "rfp_id", "contract_id", "title", "agency", "agency_normalized",
    "award_date", "awarded_vendor", "awarded_vendor_normalized", "awarded_amount",
]

# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (compatible; ContractSweeper/1.0; PR procurement research)",
        "Accept": "application/json, text/html, */*",
        "Accept-Language": "es-PR,es;q=0.9,en;q=0.8",
        "Referer": COMPRAS_BASE,
    })
    return s


def _try_get(session, url, params, logger) -> requests.Response | None:
    for attempt in range(MAX_RETRIES):
        try:
            resp = session.get(url, params=params, timeout=30)
            time.sleep(PAGE_SLEEP)
            return resp
        except requests.RequestException as exc:
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_BACKOFF[attempt])
            else:
                logger.error(f"  Request failed: {exc}")
    return None


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------

def _fetch_json_endpoint(session, endpoint: str, record_type: str,
                         max_pages: int, logger) -> list[dict]:
    url = COMPRAS_BASE + endpoint
    all_records = []
    for page in range(1, max_pages + 1):
        params = {"page": page, "per_page": PAGE_SIZE,
                  "pageSize": PAGE_SIZE, "limit": PAGE_SIZE}
        resp = _try_get(session, url, params, logger)
        if resp is None or resp.status_code >= 400:
            break
        try:
            data = resp.json()
        except (ValueError, requests.exceptions.JSONDecodeError):
            break
        if isinstance(data, list):
            all_records.extend(data)
            if len(data) < PAGE_SIZE:
                break
        elif isinstance(data, dict):
            items = (
                data.get("data") or data.get("results") or
                data.get(record_type) or data.get("items") or []
            )
            all_records.extend(items)
            if len(items) < PAGE_SIZE or not data.get("next"):
                break
        else:
            break
        if page % 20 == 0:
            logger.info(f"    {record_type}: page {page}, {len(all_records):,} records so far")
    return all_records


def _fetch_html_table(session, endpoint: str, logger) -> list[dict]:
    """Fall back to HTML table parsing if JSON endpoint is unavailable."""
    try:
        from html.parser import HTMLParser

        url = COMPRAS_BASE + endpoint
        resp = _try_get(session, url, {}, logger)
        if resp is None or resp.status_code >= 400:
            return []
        # Very basic: look for JSON embedded in script tags
        text = resp.text
        json_pattern = re.compile(r'window\.__DATA__\s*=\s*(\{.*?\});', re.DOTALL)
        m = json_pattern.search(text)
        if m:
            try:
                data = json.loads(m.group(1))
                return data.get("data") or data.get("results") or []
            except (ValueError, KeyError):
                pass
    except Exception:
        pass
    return []


# ---------------------------------------------------------------------------
# Transform
# ---------------------------------------------------------------------------

def _normalize_rfp(r: dict) -> dict:
    def _f(*keys):
        for k in keys:
            v = r.get(k) or r.get(k.lower())
            if v is not None:
                return str(v).strip()
        return ""

    agency = _f("agency", "agencia", "entity", "entidad", "department")
    val = _f("estimated_value", "estimated_amount", "budget", "presupuesto")
    try:
        val_f = float(val.replace(",", "").replace("$", "")) if val else 0.0
    except ValueError:
        val_f = 0.0

    return {
        "rfp_id":         _f("id", "rfp_id", "solicitation_id", "numero"),
        "title":          _f("title", "titulo", "description", "descripcion"),
        "agency":         agency,
        "agency_normalized": _normalize_name(agency),
        "posted_date":    _f("posted_date", "fecha_publicacion", "created_at", "date_posted"),
        "due_date":       _f("due_date", "fecha_cierre", "closing_date", "deadline"),
        "estimated_value": val_f,
        "status":         _f("status", "estado", "phase"),
    }


def _normalize_award(r: dict) -> dict:
    def _f(*keys):
        for k in keys:
            v = r.get(k) or r.get(k.lower())
            if v is not None:
                return str(v).strip()
        return ""

    agency = _f("agency", "agencia", "entity", "entidad")
    vendor = _f("vendor", "awarded_vendor", "contractor", "contratista", "awardee")
    amt = _f("awarded_amount", "contract_amount", "monto", "amount")
    try:
        amt_f = float(amt.replace(",", "").replace("$", "")) if amt else 0.0
    except ValueError:
        amt_f = 0.0

    return {
        "rfp_id":                   _f("rfp_id", "solicitation_id", "rfp_number"),
        "contract_id":              _f("id", "contract_id", "contrato_id", "numero"),
        "title":                    _f("title", "titulo", "description"),
        "agency":                   agency,
        "agency_normalized":        _normalize_name(agency),
        "award_date":               _f("award_date", "fecha_adjudicacion", "date_awarded"),
        "awarded_vendor":           vendor,
        "awarded_vendor_normalized": _normalize_name(vendor),
        "awarded_amount":           amt_f,
    }


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------

def run(root: Path = None, force: bool = False, max_pages: int = DEFAULT_MAX_PAGES) -> dict:
    root = Path(root or PROJECT_ROOT)
    raw_dir  = root / "data" / "staging" / "raw" / "compras"
    out_dir  = root / "data" / "staging" / "processed"
    raw_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)

    rfp_out   = out_dir / "pr_compras_rfps.csv"
    award_out = out_dir / "pr_compras_awards.csv"

    logger = setup_logging("download_compras", log_dir=root / "data" / "logs")

    if rfp_out.exists() and award_out.exists() and not force:
        rfp_rows   = sum(1 for _ in open(rfp_out)) - 1
        award_rows = sum(1 for _ in open(award_out)) - 1
        logger.info(f"  Compras: {rfp_rows:,} RFPs, {award_rows:,} awards — skipping (use --force).")
        return {"status": "CACHED", "rfp_rows": rfp_rows, "award_rows": award_rows}

    session = _session()
    results = {"rfps": [], "awards": []}

    for record_type, endpoints in COMPRAS_ENDPOINTS.items():
        for endpoint in endpoints:
            logger.info(f"  Trying Compras {record_type}: {endpoint}")
            records = _fetch_json_endpoint(session, endpoint, record_type, max_pages, logger)
            if not records:
                records = _fetch_html_table(session, endpoint, logger)
            if records:
                logger.info(f"  Found {len(records):,} {record_type} at {endpoint}")
                results[record_type] = records
                break
            logger.debug(f"    No data at {endpoint}")

    def _write(records, normalizer, columns, out_path, raw_path, label):
        if not records:
            logger.warning(
                f"  Compras {label}: no data retrieved.\n"
                f"  Manual export: visit {COMPRAS_BASE} and export to CSV."
            )
            pd.DataFrame(columns=columns).to_csv(out_path, index=False)
            return 0
        raw_path.write_text(json.dumps(records, ensure_ascii=False, indent=2))
        normalized = [normalizer(r) for r in records]
        df = pd.DataFrame(normalized, columns=columns).drop_duplicates()
        df.to_csv(out_path, index=False)
        logger.info(f"  Compras {label}: {len(df):,} rows → {out_path.name}")
        return len(df)

    rfp_rows = _write(
        results["rfps"], _normalize_rfp, RFP_COLUMNS,
        rfp_out, raw_dir / "compras_rfps_raw.json", "RFPs",
    )
    award_rows = _write(
        results["awards"], _normalize_award, AWARD_COLUMNS,
        award_out, raw_dir / "compras_awards_raw.json", "awards",
    )

    status = "OK" if (rfp_rows > 0 or award_rows > 0) else "EMPTY"
    return {"status": status, "rfp_rows": rfp_rows, "award_rows": award_rows}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Download Compras PR procurement data")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--max-pages", type=int, default=DEFAULT_MAX_PAGES,
                        help=f"Max pages per endpoint (default: {DEFAULT_MAX_PAGES})")
    args = parser.parse_args()
    result = run(force=args.force, max_pages=args.max_pages)
    return 0 if result.get("status") in ("OK", "CACHED") else 1


if __name__ == "__main__":
    sys.exit(main())
