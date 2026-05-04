"""
Download publicly available HUD CDBG-DR data for Puerto Rico.

This script does NOT require DRGR portal credentials — it uses only public
APIs and published data. Authorized local DRGR exports are handled by
ingest_hud_drgr_exports.py instead.

Public sources tried in order:
  1. USASpending API — HUD CPD grants (CFDA 14.269, 14.228) for PR
  2. HUD EGIS / CPD Maps ArcGIS REST service — CDBG-DR projects layer
  3. HUD public QPR/program page — HTML scrape for grant numbers/amounts

Output:
  data/normalized/hud_drgr_grants.parquet

Usage:
  python3 scripts/download_hud_drgr_public.py
  python3 scripts/download_hud_drgr_public.py --force
"""

import argparse
import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import requests

from scripts.parquet_utils import pq_read, pq_write
from scripts.config import PROJECT_ROOT, setup_logging
from scripts.build_unified_master import _normalize_name

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

NORMALIZED_DIR = PROJECT_ROOT / "data" / "normalized"
OUTPUT_PATH = NORMALIZED_DIR / "hud_drgr_grants.parquet"

MAX_RETRIES = 3
RETRY_BACKOFF = [5, 15, 30]
PAGE_SLEEP = 0.5

DRGR_GRANT_COLUMNS = [
    "grant_number",
    "grantee_name",
    "grantee_normalized",
    "disaster_number",
    "appropriation_year",
    "award_date",
    "grant_amount",
    "amount_drawn",
    "amount_remaining",
    "program_type",   # "CDBG-DR", "CDBG-MIT", "CDBG-NDR"
    "cfda_number",
    "source_system",
    "pull_date",
]

# CFDA numbers for HUD CDBG-DR programs
CFDA_CDBG_DR  = "14.269"
CFDA_CDBG_MIT = "14.228"

# USASpending API
USA_SPENDING_URL = "https://api.usaspending.gov/api/v2/search/spending_by_award/"

# HUD EGIS ArcGIS REST
HUD_EGIS_BASE = "https://egis.hud.gov/arcgis/rest/services"
EGIS_CDBG_ENDPOINTS = [
    "/CPD/CDBG_DR/MapServer/0/query",
    "/CPD/CDBG_Entitlement/MapServer/0/query",
    "/HUD/CDBGDR/MapServer/0/query",
]

# HUD public program page
HUD_CPD_URL = "https://www.hud.gov/program_offices/comm_planning/cdbg-dr/"

# ---------------------------------------------------------------------------
# HTTP session
# ---------------------------------------------------------------------------

def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (compatible; ContractSweeper/1.0; PR recovery research)",
        "Accept": "application/json, text/html, */*",
        "Accept-Language": "en-US,en;q=0.9,es;q=0.8",
    })
    return s


def _get(session, url, params, logger) -> requests.Response | None:
    for attempt in range(MAX_RETRIES):
        try:
            resp = session.get(url, params=params, timeout=30)
            if resp.status_code == 429:
                logger.warning("Rate-limited; sleeping 30s")
                time.sleep(30)
                continue
            time.sleep(PAGE_SLEEP)
            return resp
        except requests.RequestException as exc:
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_BACKOFF[attempt])
            else:
                logger.error(f"Request failed after {MAX_RETRIES} attempts: {exc}")
    return None


def _post(session, url, payload, logger) -> requests.Response | None:
    for attempt in range(MAX_RETRIES):
        try:
            resp = session.post(url, json=payload, timeout=60)
            if resp.status_code == 429:
                logger.warning("Rate-limited; sleeping 30s")
                time.sleep(30)
                continue
            time.sleep(PAGE_SLEEP)
            return resp
        except requests.RequestException as exc:
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_BACKOFF[attempt])
            else:
                logger.error(f"POST failed after {MAX_RETRIES} attempts: {exc}")
    return None

# ---------------------------------------------------------------------------
# Source 1: USASpending API
# ---------------------------------------------------------------------------

def _fetch_usaspending(session, logger) -> list[dict]:
    """Fetch HUD CDBG-DR and CDBG-MIT grants for Puerto Rico from USASpending."""
    logger.info("Trying USASpending API for HUD CPD grants in PR ...")
    records = []

    payload_base = {
        "filters": {
            "award_type_codes": ["02", "03", "04", "05"],
            "agencies": [
                {
                    "type": "awarding",
                    "tier": "toptier",
                    "name": "Department of Housing and Urban Development",
                }
            ],
            "place_of_performance_locations": [
                {"country": "USA", "state": "PR"}
            ],
        },
        "fields": [
            "Award ID",
            "Recipient Name",
            "Award Amount",
            "Start Date",
            "Awarding Agency",
            "CFDA Number",
            "Description",
        ],
        "page": 1,
        "limit": 100,
        "sort": "Award Amount",
        "order": "desc",
    }

    for cfda in [CFDA_CDBG_DR, CFDA_CDBG_MIT]:
        payload = dict(payload_base)
        payload["filters"] = dict(payload_base["filters"])
        payload["filters"]["program_numbers"] = [cfda]
        payload["page"] = 1

        while True:
            resp = _post(session, USA_SPENDING_URL, payload, logger)
            if resp is None or resp.status_code != 200:
                logger.warning(f"  USASpending: non-200 for CFDA {cfda} (page {payload['page']})")
                break
            try:
                data = resp.json()
            except ValueError:
                logger.warning("  USASpending: invalid JSON response")
                break

            results = data.get("results", [])
            if not results:
                break

            for r in results:
                amount = _safe_float(r.get("Award Amount"))
                prog = "CDBG-DR" if cfda == CFDA_CDBG_DR else "CDBG-MIT"
                records.append({
                    "grant_number":        r.get("Award ID", ""),
                    "grantee_name":        r.get("Recipient Name", ""),
                    "grantee_normalized":  _normalize_name(r.get("Recipient Name", "")),
                    "disaster_number":     "",
                    "appropriation_year":  _year_from_date(r.get("Start Date", "")),
                    "award_date":          r.get("Start Date", ""),
                    "grant_amount":        amount,
                    "amount_drawn":        None,
                    "amount_remaining":    None,
                    "program_type":        prog,
                    "cfda_number":         cfda,
                    "source_system":       "USASpending",
                    "pull_date":           str(date.today()),
                })

            # pagination
            total_pages = data.get("page_metadata", {}).get("last_page", 1)
            if payload["page"] >= total_pages:
                break
            payload["page"] += 1

    logger.info(f"  USASpending returned {len(records)} records")
    return records


# ---------------------------------------------------------------------------
# Source 2: HUD EGIS / CPD Maps ArcGIS REST
# ---------------------------------------------------------------------------

def _fetch_egis(session, logger) -> list[dict]:
    """Fetch CDBG-DR projects from HUD EGIS ArcGIS REST service."""
    logger.info("Trying HUD EGIS ArcGIS REST service ...")
    records = []

    params = {
        "where":        "STATE_CD='PR' OR STATE='PR' OR STATE_CODE='PR'",
        "outFields":    "*",
        "f":            "json",
        "resultOffset": 0,
        "resultRecordCount": 1000,
    }

    for endpoint in EGIS_CDBG_ENDPOINTS:
        url = HUD_EGIS_BASE + endpoint
        offset = 0
        endpoint_records = []

        while True:
            params["resultOffset"] = offset
            resp = _get(session, url, params, logger)
            if resp is None or resp.status_code != 200:
                break
            try:
                data = resp.json()
            except ValueError:
                break

            features = data.get("features", [])
            if not features:
                break

            for feat in features:
                attrs = feat.get("attributes", {})
                grantee = (
                    attrs.get("GRANTEE_NAME") or attrs.get("GRANTEE") or
                    attrs.get("NAME") or attrs.get("RECIPIENT_NAME") or ""
                )
                grant_num = (
                    attrs.get("GRANT_NUMBER") or attrs.get("GRANT_ID") or
                    attrs.get("AWARD_ID") or attrs.get("GRANTEE_ID") or ""
                )
                amount = _safe_float(
                    attrs.get("GRANT_AMOUNT") or attrs.get("AWARD_AMOUNT") or
                    attrs.get("TOTAL_ALLOCATION") or 0
                )
                drawn = _safe_float(
                    attrs.get("AMOUNT_DRAWN") or attrs.get("DISBURSED") or
                    attrs.get("TOTAL_DRAWN") or 0
                )
                endpoint_records.append({
                    "grant_number":       str(grant_num),
                    "grantee_name":       str(grantee),
                    "grantee_normalized": _normalize_name(str(grantee)),
                    "disaster_number":    str(attrs.get("DISASTER_NUMBER", "")),
                    "appropriation_year": _safe_int(attrs.get("APPROP_YEAR") or attrs.get("YEAR")),
                    "award_date":         str(attrs.get("AWARD_DATE", "")),
                    "grant_amount":       amount,
                    "amount_drawn":       drawn,
                    "amount_remaining":   (amount - drawn) if (amount and drawn) else None,
                    "program_type":       str(attrs.get("PROGRAM_TYPE", "CDBG-DR")),
                    "cfda_number":        str(attrs.get("CFDA", attrs.get("CFDA_NUMBER", ""))),
                    "source_system":      "HUD_EGIS",
                    "pull_date":          str(date.today()),
                })

            offset += len(features)
            exceeds = data.get("exceededTransferLimit", False)
            if not exceeds:
                break

        if endpoint_records:
            logger.info(f"  EGIS endpoint {endpoint}: {len(endpoint_records)} features")
            records.extend(endpoint_records)
            break  # Use first successful endpoint
        else:
            logger.debug(f"  EGIS endpoint {endpoint}: no data")

    logger.info(f"  EGIS returned {len(records)} records total")
    return records


# ---------------------------------------------------------------------------
# Source 3: HUD public QPR HTML page
# ---------------------------------------------------------------------------

def _fetch_hud_html(session, logger) -> list[dict]:
    """Scrape HUD CDBG-DR program page for grant numbers and amounts."""
    logger.info("Trying HUD public CDBG-DR program page ...")
    records = []

    resp = _get(session, HUD_CPD_URL, {}, logger)
    if resp is None or resp.status_code != 200:
        logger.warning("  HUD CPD page: failed to fetch")
        return records

    import re
    html = resp.text

    # Look for grant number patterns like B-17-DL-72-0001 (DR grants to PR)
    grant_pattern = re.compile(
        r"B-\d{2}-(?:DL|DG|MF|DF|DN)-72-\d{4}",
        re.IGNORECASE,
    )
    found = set(grant_pattern.findall(html))

    # Look for dollar amounts near grant numbers
    amount_pattern = re.compile(
        r"\$\s*([\d,]+(?:\.\d+)?)\s*(?:million|billion)?",
        re.IGNORECASE,
    )

    for gn in sorted(found):
        # Try to extract amount nearby (simple heuristic)
        idx = html.find(gn)
        snippet = html[max(0, idx - 200) : idx + 300]
        amounts = amount_pattern.findall(snippet)
        amount = None
        if amounts:
            raw = amounts[0].replace(",", "")
            try:
                amount = float(raw)
                # Check for "million"/"billion" keyword nearby
                if "billion" in snippet[snippet.find(amounts[0]) : snippet.find(amounts[0]) + 20].lower():
                    amount *= 1_000_000_000
                elif "million" in snippet[snippet.find(amounts[0]) : snippet.find(amounts[0]) + 20].lower():
                    amount *= 1_000_000
            except ValueError:
                amount = None

        prog = "CDBG-MIT" if "-MF-" in gn.upper() or "-DF-" in gn.upper() else "CDBG-DR"
        records.append({
            "grant_number":       gn,
            "grantee_name":       "Puerto Rico CDBG-DR Grantee",
            "grantee_normalized": "PUERTO RICO CDBG DR GRANTEE",
            "disaster_number":    "",
            "appropriation_year": None,
            "award_date":         "",
            "grant_amount":       amount,
            "amount_drawn":       None,
            "amount_remaining":   None,
            "program_type":       prog,
            "cfda_number":        CFDA_CDBG_DR if prog == "CDBG-DR" else CFDA_CDBG_MIT,
            "source_system":      "HUD_HTML",
            "pull_date":          str(date.today()),
        })

    logger.info(f"  HUD HTML page: found {len(records)} grant number(s)")
    return records


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_float(val) -> float | None:
    if val is None:
        return None
    try:
        return float(str(val).replace(",", "").strip())
    except (ValueError, TypeError):
        return None


def _safe_int(val) -> int | None:
    if val is None:
        return None
    try:
        return int(str(val).strip())
    except (ValueError, TypeError):
        return None


def _year_from_date(date_str: str) -> int | None:
    if not date_str:
        return None
    try:
        return int(str(date_str).split("-")[0])
    except (ValueError, IndexError):
        return None


def _empty_df() -> pd.DataFrame:
    return pd.DataFrame(columns=DRGR_GRANT_COLUMNS)


def _deduplicate(records: list[dict]) -> pd.DataFrame:
    """Merge records from multiple sources, deduplicating by grant_number."""
    if not records:
        return _empty_df()

    df = pd.DataFrame(records, columns=DRGR_GRANT_COLUMNS)
    df = df.drop_duplicates(subset=["grant_number"], keep="first")
    df = df.reset_index(drop=True)
    return df


# ---------------------------------------------------------------------------
# run()
# ---------------------------------------------------------------------------

def run(root=None, force=False) -> dict:
    """
    Download publicly available HUD CDBG-DR grant data for Puerto Rico.

    Returns:
        {"rows": int, "path": str, "status": "OK"/"EMPTY"/"CACHED"}
    """
    if root is not None:
        out_path = Path(root) / "data" / "normalized" / "hud_drgr_grants.parquet"
    else:
        out_path = OUTPUT_PATH

    out_path.parent.mkdir(parents=True, exist_ok=True)

    logger = setup_logging("download_hud_drgr_public")

    if out_path.exists() and not force:
        logger.info(f"Cached output found: {out_path}  (use --force to refresh)")
        try:
            df = pq_read(out_path)
            return {"rows": len(df), "path": str(out_path), "status": "CACHED"}
        except Exception:
            pass  # re-download if unreadable

    logger.info("=== download_hud_drgr_public: starting ===")

    session = _session()
    all_records: list[dict] = []

    # --- Source 1: USASpending ---
    try:
        records = _fetch_usaspending(session, logger)
        all_records.extend(records)
    except Exception as exc:
        logger.warning(f"USASpending fetch failed: {exc}")

    # --- Source 2: HUD EGIS ---
    try:
        records = _fetch_egis(session, logger)
        all_records.extend(records)
    except Exception as exc:
        logger.warning(f"HUD EGIS fetch failed: {exc}")

    # --- Source 3: HUD HTML ---
    try:
        records = _fetch_hud_html(session, logger)
        all_records.extend(records)
    except Exception as exc:
        logger.warning(f"HUD HTML fetch failed: {exc}")

    # Deduplicate and build DataFrame
    df = _deduplicate(all_records)
    status = "OK" if len(df) > 0 else "EMPTY"

    if status == "EMPTY":
        logger.warning(
            "All public sources returned zero records. Writing empty schema.\n"
            "To supplement this data, manually export from the DRGR portal:\n"
            "  1. Log in at https://drgr.hud.gov/\n"
            "  2. Navigate to Reports > Grant Summary\n"
            "  3. Export to CSV and place in data/raw/HUD DRGR/ or data/raw/HUD/\n"
            "  4. Run: python3 scripts/ingest_hud_drgr_exports.py"
        )
        df = _empty_df()

    pq_write(df, out_path)
    logger.info(f"Wrote {len(df)} rows -> {out_path}  [status={status}]")

    return {"rows": len(df), "path": str(out_path), "status": status}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Download publicly available HUD CDBG-DR data for Puerto Rico."
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-download even if output already exists.",
    )
    args = parser.parse_args()

    result = run(force=args.force)
    print(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
