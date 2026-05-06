"""
Download PRASA (Puerto Rico Aqueduct and Sewer Authority) contract data.

Source hierarchy (fetch-first / manual-fallback / graceful-empty):
  1. Manual CSV/Excel files in data/raw/PRASA/   (highest confidence)
  2. acueductos.pr.gov/compras                   (AAA Sistema Integrado de Compras)
  3. acueductos.pr.gov/transparencia             (transparency portal)
  4. Filter pr_compras_awards.csv for PRASA keywords (downstream fallback)

Output:
  data/staging/processed/pr_prasa_contracts.csv

Usage:
  python3 scripts/download_prasa.py
  python3 scripts/download_prasa.py --force
"""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from scripts.build_unified_master import _normalize_name
from scripts.config import PROJECT_ROOT, PROCESSED_DIR, setup_logging
from scripts.web_fetch import (
    extract_json_from_html_page,
    fetch_paginated_json,
    session_with_headers,
)

RAW_DIRS = [
    PROJECT_ROOT / "data" / "raw" / "PRASA",
    PROJECT_ROOT / "data" / "raw" / "prasa",
]

PRASA_COLUMNS = [
    "contract_id", "vendor_name", "vendor_normalized",
    "contract_type", "contract_value",
    "award_date", "start_date", "end_date", "status",
    "description", "municipality", "source_file",
]

PRASA_ENDPOINTS = [
    "https://acueductos.pr.gov/compras/api/contratos",
    "https://acueductos.pr.gov/api/contratos",
    "https://acueductos.pr.gov/compras/",
    "https://acueductos.pr.gov/transparencia/contratos",
    "https://acueductos.pr.gov/transparencia/",
]

PRASA_KEYWORDS = {"prasa", "acueductos", "aaa", "puerto rico aqueduct", "autoridad de acueductos"}

PAGE_SIZE = 500
MAX_RETRIES = 3
RETRY_BACKOFF = [5, 15, 30]
REQUEST_SLEEP = 1.0

COL_MAP = {
    "contract_id":    ["Contrato", "Contract Number", "contract_id", "ID", "Número"],
    "vendor_name":    ["Contratista", "Vendor", "Proveedor", "Contractor", "vendor_name", "nombre"],
    "contract_type":  ["Tipo", "Type", "contract_type"],
    "contract_value": ["Monto", "Amount", "Value", "contract_value", "valor"],
    "award_date":     ["Fecha de Adjudicación", "Award Date", "award_date", "fecha"],
    "start_date":     ["Fecha de Inicio", "Start Date", "start_date"],
    "end_date":       ["Fecha de Expiración", "End Date", "end_date"],
    "status":         ["Estado", "Status", "status"],
    "description":    ["Descripción", "Description", "description"],
    "municipality":   ["Municipio", "Municipality", "municipality"],
}


def _session():
    return session_with_headers({
        "User-Agent": "Mozilla/5.0 (compatible; ContractSweeper/1.0; PR procurement research)",
        "Referer": "https://acueductos.pr.gov/",
    })


def _try_json_endpoint(session, url, logger):
    records = fetch_paginated_json(
        session,
        url,
        params={"limit": PAGE_SIZE},
        page_param="page",
        page_size_param="per_page",
        page_size=PAGE_SIZE,
        max_pages=100,
        logger=logger,
        items_keys=["data", "results", "items", "contracts"],
    )
    if records:
        return records

    # If the endpoint returns HTML, attempt to extract embedded JSON from the page.
    embedded = extract_json_from_html_page(session, url, logger=logger)
    if isinstance(embedded, list):
        return embedded
    if isinstance(embedded, dict):
        return embedded.get("data") or embedded.get("results") or embedded.get("items") or embedded.get("contracts") or []
    return []


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
    result["vendor_normalized"] = result["vendor_name"].apply(_normalize_name)
    result["source_file"] = source_file
    for col in PRASA_COLUMNS:
        if col not in result.columns:
            result[col] = ""
    return result[PRASA_COLUMNS]


def _try_manual_files(logger):
    all_dfs = []
    for raw_dir in RAW_DIRS:
        if not raw_dir.exists():
            continue
        for pattern in ("*.csv", "*.xlsx", "*.xls"):
            for f in raw_dir.glob(pattern):
                if f.name.startswith("."):
                    continue
                logger.info(f"  Reading manual PRASA file: {f.name}")
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
    return pd.DataFrame(columns=PRASA_COLUMNS)


def _try_compras_fallback(root, logger):
    """Filter pr_compras_awards.csv for PRASA/AAA vendors."""
    compras_path = root / "data" / "staging" / "processed" / "pr_compras_awards.csv"
    if not compras_path.exists():
        return pd.DataFrame(columns=PRASA_COLUMNS)
    try:
        df = pd.read_csv(compras_path, dtype=str, low_memory=False)
        agency_col = None
        for col in ["agency", "awarding_agency", "awarding_sub_agency", "Agency"]:
            if col in df.columns:
                agency_col = col
                break
        if agency_col:
            mask = df[agency_col].str.lower().str.contains(
                "|".join(PRASA_KEYWORDS), na=False, case=False
            )
            df_prasa = df[mask].copy()
            if not df_prasa.empty:
                logger.info(f"  Found {len(df_prasa):,} PRASA rows in pr_compras_awards.csv")
                return _normalize_df(df_prasa, "pr_compras_awards.csv")
    except Exception as e:
        logger.warning(f"  Compras fallback failed: {e}")
    return pd.DataFrame(columns=PRASA_COLUMNS)


def run(root=None, force=False):
    root = Path(root or PROJECT_ROOT)
    out_path = root / "data" / "staging" / "processed" / "pr_prasa_contracts.csv"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    logger = setup_logging("download_prasa")

    if out_path.exists() and not force:
        rows = sum(1 for _ in open(out_path)) - 1
        logger.info(f"  pr_prasa_contracts.csv exists ({rows:,} rows) — skipping.")
        return {"status": "CACHED", "rows": rows}

    # 1. Remote API and portal fetch
    session = _session()
    for url in PRASA_ENDPOINTS:
        logger.info(f"  Trying remote PRASA endpoint: {url}")
        records = _try_json_endpoint(session, url, logger)
        if records:
            logger.info(f"  Found {len(records):,} PRASA records at {url}")
            df = _normalize_df(pd.DataFrame(records), "api")
            df.to_csv(out_path, index=False, encoding="utf-8")
            return {"status": "OK", "rows": len(df)}

    # 2. Compras fallback via purchase portal filter
    df = _try_compras_fallback(root, logger)
    if not df.empty:
        df.to_csv(out_path, index=False, encoding="utf-8")
        logger.info(f"  PRASA (compras fallback): {len(df):,} rows")
        return {"status": "OK", "rows": len(df)}

    # 3. Manual files as last resort
    df = _try_manual_files(logger)
    if not df.empty:
        df.to_csv(out_path, index=False, encoding="utf-8")
        logger.info(f"  PRASA (manual): {len(df):,} rows")
        return {"status": "OK", "rows": len(df)}

    # 4. Graceful empty
    logger.warning(
        "  No PRASA data found. Manual instructions:\n"
        "  Visit: https://acueductos.pr.gov/compras or https://acueductos.pr.gov/transparencia\n"
        "  Download contract data and place in data/raw/PRASA/"
    )
    pd.DataFrame(columns=PRASA_COLUMNS).to_csv(out_path, index=False, encoding="utf-8")
    return {"status": "EMPTY", "rows": 0}


def main():
    parser = argparse.ArgumentParser(description="Download PRASA contract data")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    result = run(force=args.force)
    print(f"\nPRASA: {result['rows']:,} contracts ({result['status']})")
    return 0 if result["status"] in ("OK", "CACHED") else 1


if __name__ == "__main__":
    sys.exit(main())
