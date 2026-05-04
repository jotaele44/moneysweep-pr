"""
Download PR active contractor registry from government supplier databases.

Source hierarchy (fetch-first / manual-fallback / graceful-empty):
  1. Manual files in data/raw/Active Contractor Listing/
  2. asg.pr.gov/suplidores       (ASG supplier pages)
  3. consultacontratos.ocpr.gov.pr (OCPR contract registry)
  4. hacienda.pr.gov             (Hacienda supplier list)
  5. subastas.pr.gov             (RUS)

Output:
  data/staging/processed/pr_active_contractors.csv

Usage:
  python3 scripts/download_active_contractors.py
  python3 scripts/download_active_contractors.py --force
"""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import requests

from scripts.build_unified_master import _normalize_name
from scripts.config import PROJECT_ROOT, PROCESSED_DIR, setup_logging

RAW_DIRS = [
    PROJECT_ROOT / "data" / "raw" / "Active Contractor Listing",
    PROJECT_ROOT / "data" / "raw" / "active_contractors",
    PROJECT_ROOT / "data" / "raw" / "Active Contractors",
]

CONTRACTOR_COLUMNS = [
    "entity_name", "entity_normalized",
    "registration_id", "registration_date", "expiry_date",
    "contractor_type", "naics_code", "municipality",
    "status",
    "source_file",
]

ENDPOINTS = [
    "https://asg.pr.gov/api/suplidores",
    "https://asg.pr.gov/suplidores/api/vendors",
    "https://asg.pr.gov/suplidores/",
    "https://consultacontratos.ocpr.gov.pr/api/suplidores",
    "https://consultacontratos.ocpr.gov.pr/suplidores",
    "https://hacienda.pr.gov/api/suplidores",
    "https://hacienda.pr.gov/suplidores/",
    "https://subastas.pr.gov/api/vendors",
    "https://subastas.pr.gov/",
]

PAGE_SIZE = 500
MAX_RETRIES = 3
RETRY_BACKOFF = [5, 15, 30]
REQUEST_SLEEP = 1.0

COL_MAP = {
    "entity_name":       ["Nombre", "Company Name", "Vendor Name", "Suplidor", "entity_name", "name", "nombre"],
    "registration_id":   ["Registro", "Registration ID", "ID", "registration_id", "num_registro"],
    "registration_date": ["Fecha de Registro", "Registration Date", "registration_date", "fecha"],
    "expiry_date":       ["Fecha de Expiración", "Expiry Date", "expiry_date", "fecha_expiracion"],
    "contractor_type":   ["Tipo", "Type", "Category", "contractor_type", "clase"],
    "naics_code":        ["NAICS", "NAICS Code", "Código NAICS", "naics_code"],
    "municipality":      ["Municipio", "Municipality", "City", "municipality"],
    "status":            ["Estado", "Status", "Active", "status", "activo"],
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
            records = data.get("data", data.get("results", data.get("vendors", data.get("suplidores", []))))
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


def _normalize_df(df, source_file):
    out = {}
    for out_col, candidates in COL_MAP.items():
        src = _map_col(df.columns.tolist(), candidates)
        out[out_col] = df[src].astype(str) if src else ""
    result = pd.DataFrame(out)
    result["entity_normalized"] = result["entity_name"].apply(_normalize_name)
    result["source_file"] = source_file
    for col in CONTRACTOR_COLUMNS:
        if col not in result.columns:
            result[col] = ""
    return result[CONTRACTOR_COLUMNS]


def _try_manual_files(logger):
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
                        mapped = _normalize_df(df, f.name)
                        all_dfs.append(mapped)
                        logger.info(f"    → {len(df):,} rows")
                except Exception as e:
                    logger.warning(f"    Failed: {e}")
    if all_dfs:
        return pd.concat(all_dfs, ignore_index=True)
    return pd.DataFrame(columns=CONTRACTOR_COLUMNS)


def run(root=None, force=False):
    root = Path(root or PROJECT_ROOT)
    out_path = root / "data" / "staging" / "processed" / "pr_active_contractors.csv"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    logger = setup_logging("download_active_contractors")

    if out_path.exists() and not force:
        rows = sum(1 for _ in open(out_path)) - 1
        logger.info(f"  pr_active_contractors.csv exists ({rows:,} rows) — skipping.")
        return {"status": "CACHED", "rows": rows}

    # 1. Manual files
    df = _try_manual_files(logger)
    if not df.empty:
        df.to_csv(out_path, index=False, encoding="utf-8")
        logger.info(f"  Active contractors (manual): {len(df):,} rows")
        return {"status": "OK", "rows": len(df)}

    # 2. API endpoints
    session = _session()
    for url in ENDPOINTS:
        logger.info(f"  Trying: {url}")
        records = _try_json_endpoint(session, url, logger)
        if records:
            logger.info(f"  Found {len(records):,} records at {url}")
            df = _normalize_df(pd.DataFrame(records), "api")
            df.to_csv(out_path, index=False, encoding="utf-8")
            return {"status": "OK", "rows": len(df)}

    # 3. Graceful empty
    logger.warning(
        "  No active contractor data found. Manual instructions:\n"
        "  Visit: https://asg.pr.gov/suplidores or https://consultacontratos.ocpr.gov.pr\n"
        "  Download the supplier registry and place in data/raw/Active Contractor Listing/"
    )
    pd.DataFrame(columns=CONTRACTOR_COLUMNS).to_csv(out_path, index=False, encoding="utf-8")
    return {"status": "EMPTY", "rows": 0}


def main():
    parser = argparse.ArgumentParser(description="Download PR active contractor registry")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    result = run(force=args.force)
    print(f"\nActive contractors: {result['rows']:,} records ({result['status']})")
    return 0 if result["status"] in ("OK", "CACHED") else 1


if __name__ == "__main__":
    sys.exit(main())
