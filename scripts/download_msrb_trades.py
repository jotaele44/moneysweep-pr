"""
Download MSRB RTRS (Real-Time Reporting System) secondary market trade data
for Puerto Rico municipal bond CUSIPs.

Secondary market trades reveal which broker-dealers are actively trading PR
bonds — these dealer entities can then be cross-referenced against federal
award recipients to identify dual-role financial actors.

Source:
  MSRB EMMA trade data API — per-CUSIP trade history, or bulk state export.
  If the MSRB trade API is blocked, the script writes an empty output and logs
  a manual download path. It never crashes the pipeline.

Inputs:
  data/staging/processed/pr_emma_bonds.csv  — PR CUSIP list (from download_emma.py)

Output:
  data/staging/processed/pr_msrb_trades.csv

Usage:
  python3 scripts/download_msrb_trades.py
  python3 scripts/download_msrb_trades.py --force
  python3 scripts/download_msrb_trades.py --max-cusips 200
"""

import argparse
import io
import sys
import time
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import requests

from scripts.config import PROCESSED_DIR, PROJECT_ROOT, setup_logging
from scripts.build_unified_master import _normalize_name

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EMMA_BASE     = "https://emma.msrb.org"
PAGE_SLEEP    = 0.3
MAX_RETRIES   = 3
RETRY_BACKOFF = [5, 15, 30]

# Per-CUSIP trade history endpoint
TRADE_CUSIP_ENDPOINT = "/TradeData/GetSecuritiesTradeData"

# Bulk trade export by state and year
TRADE_BULK_ENDPOINTS = [
    "/TradeData/BulkDownload",
    "/api/TradeData/GetTradesByState",
]

# Max CUSIPs to query individually (avoid hammering the API)
DEFAULT_MAX_CUSIPS = 500
YEARS_BACK = 5  # pull trades for the last N fiscal years

OUTPUT_COLUMNS = [
    "cusip", "trade_date", "settlement_date",
    "par_traded", "price", "yield",
    "dealer_id", "dealer_name", "dealer_normalized",
    "trade_type",   # B=buy from customer, S=sell to customer, D=interdealer
    "market_side",  # customer | interdealer
]

# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (compatible; ContractSweeper/1.0; PR bond research)",
        "Accept":     "application/json, text/html, */*",
        "Referer":    EMMA_BASE,
    })
    return s


def _get_json(session, url, params, logger):
    for attempt in range(MAX_RETRIES):
        try:
            resp = session.get(url, params=params, timeout=60)
            if resp.status_code == 429:
                time.sleep(60)
                continue
            if 400 <= resp.status_code < 500:
                logger.debug(f"  HTTP {resp.status_code}: {url}")
                return None
            resp.raise_for_status()
            time.sleep(PAGE_SLEEP)
            try:
                return resp.json()
            except ValueError:
                return None
        except requests.RequestException as exc:
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_BACKOFF[attempt])
            else:
                logger.debug(f"  Request failed: {exc}")
    return None


def _get_bytes(session, url, params, logger) -> bytes | None:
    for attempt in range(MAX_RETRIES):
        try:
            resp = session.get(url, params=params, timeout=120, stream=True)
            if 400 <= resp.status_code < 500:
                return None
            resp.raise_for_status()
            buf = io.BytesIO()
            for chunk in resp.iter_content(1024 * 512):
                buf.write(chunk)
            return buf.getvalue()
        except requests.RequestException as exc:
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_BACKOFF[attempt])
            else:
                logger.debug(f"  Request failed: {exc}")
    return None


# ---------------------------------------------------------------------------
# Fetch strategies
# ---------------------------------------------------------------------------

def _fetch_bulk(session, logger) -> list[dict]:
    """Try bulk state-level trade export (zip or JSON)."""
    import datetime
    current_year = datetime.date.today().year

    for ep in TRADE_BULK_ENDPOINTS:
        for year in range(current_year, current_year - YEARS_BACK, -1):
            url = EMMA_BASE + ep
            params = {"stateCode": "PR", "state": "PR", "year": year}
            raw = _get_bytes(session, url, params, logger)
            if raw is None:
                continue
            # Try ZIP
            try:
                with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                    csv_files = [n for n in zf.namelist() if n.lower().endswith(".csv")]
                    if csv_files:
                        target = next((n for n in csv_files if "trade" in n.lower()), csv_files[0])
                        with zf.open(target) as f:
                            df = pd.read_csv(f, dtype=str, low_memory=False)
                        records = df.to_dict("records")
                        if records:
                            logger.info(f"    Bulk {ep} {year}: {len(records):,} trade records")
                            return records
            except zipfile.BadZipFile:
                pass
            # Try JSON
            try:
                import json
                records = json.loads(raw.decode("utf-8"))
                if isinstance(records, list) and records:
                    return records
            except Exception:
                pass
    return []


def _fetch_per_cusip(session, cusips: list[str], logger) -> list[dict]:
    """Query per-CUSIP trade history endpoint."""
    url = EMMA_BASE + TRADE_CUSIP_ENDPOINT
    all_records: list[dict] = []
    failed = 0
    consecutive_failures = 0

    for i, cusip in enumerate(cusips):
        if consecutive_failures >= 3:
            logger.info(f"    3 consecutive failures — endpoint likely unavailable; stopping")
            break
        data = _get_json(session, url, {"cusip": cusip}, logger)
        if data is None:
            failed += 1
            consecutive_failures += 1
            continue
        consecutive_failures = 0
        if isinstance(data, list):
            records = data
        elif isinstance(data, dict):
            records = (data.get("trades") or data.get("results") or
                       data.get("data") or [])
        else:
            records = []
        for r in records:
            r["_cusip"] = cusip
        all_records.extend(records)
        if (i + 1) % 50 == 0:
            logger.info(f"    {i+1}/{len(cusips)} CUSIPs queried, {len(all_records):,} trades")

    if failed:
        logger.debug(f"    {failed} CUSIP queries returned no data")
    return all_records


# ---------------------------------------------------------------------------
# Normalize raw trade record → canonical schema
# ---------------------------------------------------------------------------

def _normalize_trade(r: dict) -> dict:
    def _f(*keys):
        for k in keys:
            v = r.get(k) or r.get(k.lower()) or r.get(k.upper())
            if v is not None:
                return str(v).strip()
        return ""

    def _num(*keys):
        for k in keys:
            v = r.get(k) or r.get(k.lower())
            if v is not None:
                try:
                    return float(str(v).replace(",", "").replace("$", ""))
                except ValueError:
                    pass
        return 0.0

    trade_type = _f("tradeType", "trade_type", "TradeType", "sideOfTrade", "side")
    market_side = "interdealer" if trade_type.upper() in ("D", "INTERDEALER") else "customer"
    dealer = _f("dealerName", "dealer_name", "DealerName", "brokerDealer",
                "reportingParty", "reportingPartyName")

    return {
        "cusip":             r.get("_cusip") or _f("cusip", "Cusip", "CUSIP"),
        "trade_date":        _f("tradeDate", "trade_date", "TradeDate", "executionDate"),
        "settlement_date":   _f("settlementDate", "settlement_date", "SettlementDate"),
        "par_traded":        _num("parTraded", "par_traded", "quantity", "Quantity", "parAmount"),
        "price":             _num("price", "Price", "tradePrice", "cleanPrice"),
        "yield":             _num("yield", "Yield", "tradeYield"),
        "dealer_id":         _f("dealerId", "dealer_id", "DealerId", "mpid", "MPID"),
        "dealer_name":       dealer,
        "dealer_normalized": _normalize_name(dealer),
        "trade_type":        trade_type,
        "market_side":       market_side,
    }


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------

def run(root: Path = None, force: bool = False,
        max_cusips: int = DEFAULT_MAX_CUSIPS) -> dict:
    root = Path(root or PROJECT_ROOT)
    proc = root / "data" / "staging" / "processed"
    out_path = proc / "pr_msrb_trades.csv"
    proc.mkdir(parents=True, exist_ok=True)

    logger = setup_logging("download_msrb_trades", log_dir=root / "data" / "logs")

    if out_path.exists() and not force:
        rows = sum(1 for _ in open(out_path)) - 1
        logger.info(f"  MSRB trades: {out_path.name} exists ({rows:,} rows) — skipping.")
        return {"status": "CACHED", "rows": rows}

    session = _session()
    raw_records: list[dict] = []

    # Strategy 1: bulk state export
    logger.info("  Trying MSRB RTRS bulk state export...")
    raw_records = _fetch_bulk(session, logger)

    # Strategy 2: per-CUSIP (using cusips from pr_emma_bonds.csv)
    if not raw_records:
        bonds_path = proc / "pr_emma_bonds.csv"
        if bonds_path.exists():
            df_bonds = pd.read_csv(bonds_path, dtype=str, low_memory=False)
            cusips = df_bonds["cusip"].dropna().unique().tolist()[:max_cusips]
            if cusips:
                logger.info(
                    f"  Trying per-CUSIP trade fetch for {len(cusips):,} CUSIPs..."
                )
                raw_records = _fetch_per_cusip(session, cusips, logger)
        else:
            logger.warning("  pr_emma_bonds.csv not found — run download_emma.py first")

    session.close()

    if not raw_records:
        logger.warning(
            "  MSRB RTRS: no trade data retrieved.\n"
            "  The MSRB trade API may require authentication.\n"
            "  Manual option: visit https://emma.msrb.org and search for PR CUSIP trades,\n"
            "  then export and save to data/staging/processed/pr_msrb_trades.csv"
        )
        pd.DataFrame(columns=OUTPUT_COLUMNS).to_csv(out_path, index=False)
        return {"status": "EMPTY", "rows": 0}

    # Normalize and write
    normalized = [_normalize_trade(r) for r in raw_records]
    df = pd.DataFrame(normalized, columns=OUTPUT_COLUMNS)
    df = df.drop_duplicates(subset=["cusip", "trade_date", "par_traded", "dealer_id"])
    df = df.sort_values("trade_date", ascending=False)
    df.to_csv(out_path, index=False)

    n = len(df)
    unique_dealers = df["dealer_name"].nunique()
    total_par = pd.to_numeric(df["par_traded"], errors="coerce").sum()
    logger.info(
        f"  MSRB trades: {n:,} trades, {unique_dealers:,} dealers, "
        f"${total_par:,.0f} par traded → {out_path.name}"
    )

    return {
        "status":         "OK",
        "rows":           n,
        "unique_dealers": unique_dealers,
        "total_par":      float(total_par),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Download MSRB RTRS trade data for PR municipal bonds"
    )
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--max-cusips", type=int, default=DEFAULT_MAX_CUSIPS,
                        help=f"Max CUSIPs to query individually (default: {DEFAULT_MAX_CUSIPS})")
    args = parser.parse_args()
    result = run(force=args.force, max_cusips=args.max_cusips)
    return 0 if result.get("status") in ("OK", "CACHED", "EMPTY") else 1


if __name__ == "__main__":
    sys.exit(main())
