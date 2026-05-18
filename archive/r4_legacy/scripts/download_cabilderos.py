"""
Download PR state-level lobbyist (cabilderos) registrations.

Source hierarchy (fetch-first / graceful-empty):
  1. registrodecabilderos.pr.gov  — primary discovery
  2. etica.pr.gov/cabilderos      — secondary
  3. data.pr.gov datastore        — open data fallback

Output:
  data/staging/processed/pr_cabilderos.csv

Usage:
  python3 scripts/download_cabilderos.py
  python3 scripts/download_cabilderos.py --force
"""

import argparse
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import requests

from scripts.build_unified_master import _normalize_name
from scripts.config import PROJECT_ROOT, PROCESSED_DIR, setup_logging

RAW_DIR    = PROJECT_ROOT / "data" / "raw" / "Cabilderos"
RAW_DIRS   = [RAW_DIR, PROJECT_ROOT / "data" / "raw" / "cabilderos"]

CABILDEROS_COLUMNS = [
    "lobbyist_name", "lobbyist_normalized",
    "client_name", "client_normalized",
    "registration_year", "registration_date", "expiry_date",
    "lobbying_subject", "agency_lobbied",
    "fee_amount", "source_file",
]

ENDPOINTS = [
    "https://registrodecabilderos.pr.gov/api/cabilderos",
    "https://registrodecabilderos.pr.gov/api/v1/cabilderos",
    "https://registrodecabilderos.pr.gov/cabilderos",
    "https://etica.pr.gov/api/cabilderos",
    "https://etica.pr.gov/cabilderos/search",
    "https://etica.pr.gov/cabilderos",
    "https://data.pr.gov/api/3/action/datastore_search?resource_id=cabilderos&limit=1000",
]

PAGE_SIZE = 500
MAX_RETRIES = 3
RETRY_BACKOFF = [5, 15, 30]
REQUEST_SLEEP = 1.0

COL_MAP = {
    "lobbyist_name":     ["Nombre del Cabildero", "Lobbyist Name", "Cabildero", "Name", "nombre", "lobbyist"],
    "client_name":       ["Cliente", "Client Name", "Principal", "Representado", "client", "cliente"],
    "registration_year": ["Año", "Year", "Registration Year", "año_registro"],
    "registration_date": ["Fecha de Registro", "Registration Date", "fecha_registro"],
    "expiry_date":       ["Fecha de Expiración", "Expiry Date", "fecha_expiracion"],
    "lobbying_subject":  ["Asunto", "Subject", "Tema", "lobbying_subject", "asunto"],
    "agency_lobbied":    ["Agencia", "Agency", "Cuerpo", "agency_lobbied", "agencia"],
    "fee_amount":        ["Honorarios", "Fee", "Amount", "fee_amount"],
}


def _session():
    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (compatible; ContractSweeper/1.0; PR procurement research)",
        "Accept": "application/json, text/html, */*",
        "Accept-Language": "es-PR,es;q=0.9,en;q=0.8",
    })
    return s


def _get(session, url, params, logger):
    for attempt in range(MAX_RETRIES):
        try:
            resp = session.get(url, params=params, timeout=30)
            time.sleep(REQUEST_SLEEP)
            if resp.status_code == 429:
                time.sleep(30)
                continue
            return resp
        except requests.RequestException as exc:
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_BACKOFF[attempt])
            else:
                logger.error(f"  Request failed: {exc}")
    return None


def _try_json_endpoint(session, url, logger):
    all_records = []
    page = 1
    while True:
        resp = _get(session, url, {"page": page, "per_page": PAGE_SIZE, "limit": PAGE_SIZE}, logger)
        if resp is None or resp.status_code >= 400:
            return []
        try:
            data = resp.json()
        except Exception:
            return []
        if isinstance(data, list):
            all_records.extend(data)
            if len(data) < PAGE_SIZE:
                break
            page += 1
        elif isinstance(data, dict):
            # data.pr.gov format
            result = data.get("result", data)
            records = result.get("records", result.get("data", result.get("results", [])))
            if isinstance(records, list):
                all_records.extend(records)
                if len(records) < PAGE_SIZE:
                    break
                page += 1
            else:
                break
        else:
            break
    return all_records


def _map_col(df_cols, candidates):
    cols_lower = {c.lower().strip(): c for c in df_cols}
    for cand in candidates:
        if cand in df_cols:
            return cand
        if cand.lower() in cols_lower:
            return cols_lower[cand.lower()]
    return None


def _normalize_records(records, source_file="api"):
    if not records:
        return pd.DataFrame(columns=CABILDEROS_COLUMNS)
    df = pd.DataFrame(records)
    out = {}
    for out_col, candidates in COL_MAP.items():
        src = _map_col(df.columns.tolist(), candidates)
        out[out_col] = df[src].astype(str) if src else ""
    result = pd.DataFrame(out)
    result["lobbyist_normalized"] = result["lobbyist_name"].apply(_normalize_name)
    result["client_normalized"] = result["client_name"].apply(_normalize_name)
    result["source_file"] = source_file
    for col in CABILDEROS_COLUMNS:
        if col not in result.columns:
            result[col] = ""
    return result[CABILDEROS_COLUMNS]


def _try_manual_files(logger):
    """Try reading manual CSV/Excel files from raw Cabilderos directories."""
    all_dfs = []
    for raw_dir in RAW_DIRS:
        if not raw_dir.exists():
            continue
        for pattern in ("*.csv", "*.xlsx", "*.xls"):
            for f in raw_dir.glob(pattern):
                if f.name.startswith("."):
                    continue
                logger.info(f"  Reading manual file: {f.name}")
                try:
                    if f.suffix.lower() in (".xlsx", ".xls"):
                        df = pd.read_excel(f, dtype=str)
                    else:
                        df = pd.read_csv(f, dtype=str, low_memory=False)
                    if not df.empty:
                        mapped = _normalize_records(df.to_dict("records"), f.name)
                        all_dfs.append(mapped)
                        logger.info(f"  → {len(df):,} rows from {f.name}")
                except Exception as e:
                    logger.warning(f"  Failed to read {f.name}: {e}")
    if all_dfs:
        return pd.concat(all_dfs, ignore_index=True)
    return pd.DataFrame(columns=CABILDEROS_COLUMNS)


def run(root=None, force=False):
    root = Path(root or PROJECT_ROOT)
    out_path = root / "data" / "staging" / "processed" / "pr_cabilderos.csv"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    logger = setup_logging("download_cabilderos")

    if out_path.exists() and not force:
        rows = sum(1 for _ in open(out_path)) - 1
        logger.info(f"  pr_cabilderos.csv exists ({rows:,} rows) — skipping.")
        return {"status": "CACHED", "rows": rows}

    # 1. Try manual files first
    df_manual = _try_manual_files(logger)
    if not df_manual.empty:
        logger.info(f"  Manual files: {len(df_manual):,} cabildero records")
        df_manual.to_csv(out_path, index=False, encoding="utf-8")
        return {"status": "OK", "rows": len(df_manual)}

    # 2. Try API endpoints
    session = _session()
    records = []
    for url in ENDPOINTS:
        logger.info(f"  Trying: {url}")
        records = _try_json_endpoint(session, url, logger)
        if records:
            logger.info(f"  Found {len(records):,} records at {url}")
            break

    if records:
        df = _normalize_records(records, source_file="api")
        df.to_csv(out_path, index=False, encoding="utf-8")
        logger.info(f"  pr_cabilderos.csv: {len(df):,} rows")
        return {"status": "OK", "rows": len(df)}

    # 3. Graceful empty
    logger.warning(
        "  No cabilderos data found. Manual download instructions:\n"
        "  Visit: https://registrodecabilderos.pr.gov\n"
        "  Download the lobbyist registry and place CSV/Excel files in data/raw/Cabilderos/"
    )
    pd.DataFrame(columns=CABILDEROS_COLUMNS).to_csv(out_path, index=False, encoding="utf-8")
    return {"status": "EMPTY", "rows": 0}


def main():
    parser = argparse.ArgumentParser(description="Download PR cabilderos (lobbyist) registry")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    result = run(force=args.force)
    print(f"\nCabilderos: {result['rows']:,} records ({result['status']})")
    return 0 if result["status"] in ("OK", "CACHED") else 1


if __name__ == "__main__":
    sys.exit(main())
