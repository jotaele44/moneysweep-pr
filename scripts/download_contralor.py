"""
Download Oficina del Contralor de Puerto Rico audit and contract records.

Two separate evidence layers:
  - Audits:    iapconsulta.ocpr.gov.pr (audit search portal)
  - Contracts: consultacontratos.ocpr.gov.pr (contract registry)

Both use fetch-first / manual-fallback / graceful-empty pattern.

Outputs:
  data/staging/processed/pr_contralor_audits.csv
  data/staging/processed/pr_contralor_contracts.csv

Usage:
  python3 scripts/download_contralor.py
  python3 scripts/download_contralor.py --force
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

RAW_DIR  = PROJECT_ROOT / "data" / "raw" / "Oficina del Contralor"
RAW_DIRS = [RAW_DIR, PROJECT_ROOT / "data" / "raw" / "contralor",
            PROJECT_ROOT / "data" / "raw" / "Contralor"]

CONTRALOR_AUDIT_COLUMNS = [
    "entity_name", "entity_normalized",
    "audit_id", "audit_type",
    "audit_year", "audit_date",
    "finding_count", "finding_type",
    "contract_amount", "municipality",
    "recommendation", "status",
    "source_file",
]

CONTRALOR_CONTRACT_COLUMNS = [
    "contract_id", "entity_name", "entity_normalized",
    "agency", "contract_type",
    "contract_amount", "award_date", "expiry_date",
    "description", "municipality",
    "status", "source_file",
]

AUDIT_ENDPOINTS = [
    "https://iapconsulta.ocpr.gov.pr/api/informes",
    "https://iapconsulta.ocpr.gov.pr/api/v1/informes",
    "https://iapconsulta.ocpr.gov.pr/api/audits",
    "https://www.ocpr.gov.pr/api/informes",
    "https://www.ocpr.gov.pr/informes/",
]

CONTRACT_ENDPOINTS = [
    "https://consultacontratos.ocpr.gov.pr/api/contratos",
    "https://consultacontratos.ocpr.gov.pr/api/v1/contratos",
    "https://consultacontratos.ocpr.gov.pr/contratos",
    "https://www.ocpr.gov.pr/api/contratos",
    "https://www.ocpr.gov.pr/contratos/",
]

PAGE_SIZE = 500
MAX_RETRIES = 3
RETRY_BACKOFF = [5, 15, 30]
REQUEST_SLEEP = 1.0

AUDIT_COL_MAP = {
    "entity_name":   ["Entidad", "Entity", "Municipio", "Agencia", "entity", "auditee"],
    "audit_id":      ["Número de Informe", "Report Number", "Audit ID", "informe_num", "id"],
    "audit_type":    ["Tipo", "Type", "Clase", "audit_type"],
    "audit_year":    ["Año", "Year", "audit_year", "fiscal_year"],
    "audit_date":    ["Fecha", "Date", "Issued Date", "audit_date"],
    "finding_count": ["Hallazgos", "Findings", "finding_count", "num_findings"],
    "finding_type":  ["Tipo de Hallazgo", "Finding Type", "finding_type"],
    "contract_amount": ["Monto", "Amount", "contract_amount"],
    "municipality":  ["Municipio", "Municipality", "municipality"],
    "recommendation": ["Recomendación", "Recommendation", "recommendation"],
    "status":        ["Estado", "Status", "status"],
}

CONTRACT_COL_MAP = {
    "contract_id":     ["Contrato Núm", "Contract Number", "contract_id", "num_contrato"],
    "entity_name":     ["Contratista", "Contractor", "Vendor", "entity", "nombre"],
    "agency":          ["Agencia", "Agency", "agency"],
    "contract_type":   ["Tipo", "Type", "contract_type"],
    "contract_amount": ["Monto", "Amount", "contract_amount", "valor"],
    "award_date":      ["Fecha de Firma", "Award Date", "award_date", "fecha"],
    "expiry_date":     ["Fecha de Expiración", "Expiry Date", "expiry_date"],
    "description":     ["Descripción", "Description", "Propósito", "description"],
    "municipality":    ["Municipio", "Municipality", "municipality"],
    "status":          ["Estado", "Status", "status"],
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
            records = data.get("data", data.get("results", data.get("items", [])))
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


def _map_to_schema(records, col_map, columns, source_file, name_field):
    if not records:
        return pd.DataFrame(columns=columns)
    df = pd.DataFrame(records) if isinstance(records, list) else records
    out = {}
    for out_col, candidates in col_map.items():
        src = _map_col(df.columns.tolist(), candidates)
        out[out_col] = df[src].astype(str) if src else ""
    result = pd.DataFrame(out)
    result["entity_normalized"] = result.get(name_field, pd.Series(dtype=str)).apply(_normalize_name)
    result["source_file"] = source_file
    for col in columns:
        if col not in result.columns:
            result[col] = ""
    return result[columns]


def _try_manual_files(logger, is_audit=True):
    columns = CONTRALOR_AUDIT_COLUMNS if is_audit else CONTRALOR_CONTRACT_COLUMNS
    col_map = AUDIT_COL_MAP if is_audit else CONTRACT_COL_MAP
    name_field = "entity_name"
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
                        mapped = _map_to_schema(df, col_map, columns, f.name, name_field)
                        all_dfs.append(mapped)
                except Exception as e:
                    logger.warning(f"  Failed to read {f.name}: {e}")
    if all_dfs:
        return pd.concat(all_dfs, ignore_index=True)
    return pd.DataFrame(columns=columns)


def _fetch(endpoints, col_map, columns, name_field, label, logger):
    session = _session()
    for url in endpoints:
        logger.info(f"  Trying {label}: {url}")
        records = _try_json_endpoint(session, url, logger)
        if records:
            logger.info(f"  Found {len(records):,} {label} records at {url}")
            return _map_to_schema(records, col_map, columns, "api", name_field)
    return pd.DataFrame(columns=columns)


def run(root=None, force=False):
    root = Path(root or PROJECT_ROOT)
    audit_path    = root / "data" / "staging" / "processed" / "pr_contralor_audits.csv"
    contract_path = root / "data" / "staging" / "processed" / "pr_contralor_contracts.csv"
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    logger = setup_logging("download_contralor")

    cached_audit    = audit_path.exists() and not force
    cached_contract = contract_path.exists() and not force

    if cached_audit and cached_contract:
        a_rows = sum(1 for _ in open(audit_path)) - 1
        c_rows = sum(1 for _ in open(contract_path)) - 1
        logger.info(f"  Both Contralor outputs exist ({a_rows:,} audits, {c_rows:,} contracts) — skipping.")
        return {"status": "CACHED", "audit_rows": a_rows, "contract_rows": c_rows}

    # --- Audits ---
    if not cached_audit:
        df_audits = _try_manual_files(logger, is_audit=True)
        if df_audits.empty:
            df_audits = _fetch(AUDIT_ENDPOINTS, AUDIT_COL_MAP, CONTRALOR_AUDIT_COLUMNS, "entity_name", "audits", logger)
        if df_audits.empty:
            logger.warning(
                "  No Contralor audit data. Manual instructions:\n"
                "  Visit: https://iapconsulta.ocpr.gov.pr\n"
                "  Search for PR audits and export. Place files in data/raw/Oficina del Contralor/"
            )
            df_audits = pd.DataFrame(columns=CONTRALOR_AUDIT_COLUMNS)
        df_audits.to_csv(audit_path, index=False, encoding="utf-8")
        logger.info(f"  Audits: {len(df_audits):,} rows → {audit_path.name}")

    # --- Contracts ---
    if not cached_contract:
        df_contracts = _try_manual_files(logger, is_audit=False)
        if df_contracts.empty:
            df_contracts = _fetch(CONTRACT_ENDPOINTS, CONTRACT_COL_MAP, CONTRALOR_CONTRACT_COLUMNS, "entity_name", "contracts", logger)
        if df_contracts.empty:
            logger.warning(
                "  No Contralor contract data. Manual instructions:\n"
                "  Visit: https://consultacontratos.ocpr.gov.pr\n"
                "  Search and export contracts. Place files in data/raw/Oficina del Contralor/"
            )
            df_contracts = pd.DataFrame(columns=CONTRALOR_CONTRACT_COLUMNS)
        df_contracts.to_csv(contract_path, index=False, encoding="utf-8")
        logger.info(f"  Contracts: {len(df_contracts):,} rows → {contract_path.name}")

    a_rows = len(pd.read_csv(audit_path, dtype=str)) if audit_path.exists() else 0
    c_rows = len(pd.read_csv(contract_path, dtype=str)) if contract_path.exists() else 0

    return {"status": "OK", "audit_rows": a_rows, "contract_rows": c_rows}


def main():
    parser = argparse.ArgumentParser(description="Download PR Contralor audits and contracts")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    result = run(force=args.force)
    print(f"\nContralor: {result['audit_rows']:,} audits, {result['contract_rows']:,} contracts ({result['status']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
