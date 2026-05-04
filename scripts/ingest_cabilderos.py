"""
Ingest PR Cabilderos (state-level lobbyist registry) data.

Puerto Rico's Oficina de Ética Gubernamental maintains a registry of lobbyists
(cabilderos) registered to lobby the PR Legislature and executive agencies.
Cross-referencing cabildero clients with federal award recipients reveals
entities that lobby both the PR government AND receive federal contracts —
a dual-influence signal not captured by the federal LDA pipeline.

Input:
  data/raw/Cabilderos/ — CSV or Excel files from PR Ethics Office

Output:
  data/staging/processed/pr_cabilderos.csv

Usage:
  python3 scripts/ingest_cabilderos.py
  python3 scripts/ingest_cabilderos.py --force
"""

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from scripts.config import PROJECT_ROOT, setup_logging

CABILDEROS_COLUMNS = [
    "lobbyist_name", "lobbyist_normalized",
    "client_name", "client_normalized",
    "registration_year", "registration_date", "expiry_date",
    "lobbying_subject", "agency_lobbied",
    "fee_amount", "source_file",
]

# Flexible column mapping for PR Cabilderos registry formats
COL_MAP = {
    "lobbyist_name": [
        "Nombre Cabildero", "Cabildero", "Lobbyist Name", "Nombre",
        "Nombre del Cabildero", "lobbyist", "nombre_cabildero",
    ],
    "client_name": [
        "Cliente", "Client Name", "Nombre Cliente", "Nombre del Cliente",
        "Representado", "Entidad", "Entity", "Organization",
        "nombre_cliente", "cliente",
    ],
    "registration_year": [
        "Año", "Year", "Año de Registro", "Registration Year",
        "anio", "año_registro",
    ],
    "registration_date": [
        "Fecha de Registro", "Registration Date", "Fecha Registro",
        "fecha_registro", "Date Registered",
    ],
    "expiry_date": [
        "Fecha de Expiración", "Expiry Date", "Fecha Expiracion",
        "fecha_expiracion", "Expiration Date",
    ],
    "lobbying_subject": [
        "Asunto", "Subject", "Tema", "Materia", "Area de Cabildeo",
        "lobbying_subject", "asunto",
    ],
    "agency_lobbied": [
        "Agencia", "Agency", "Agencia o Entidad", "Entity Lobbied",
        "agencia", "Cuerpo Legislativo",
    ],
    "fee_amount": [
        "Honorarios", "Fee", "Amount", "Compensación", "Compensation",
        "honorarios", "fee_amount",
    ],
}

_STRIP_RE = re.compile(r"[^\w\s]")
_SPACE_RE = re.compile(r"\s+")
_NAME_SUFFIXES = {
    "INC", "LLC", "CORP", "LTD", "CO", "LP", "LLP",
    "COMPANY", "CORPORATION", "INCORPORATED", "LIMITED",
    "CSP", "SE", "SAS",
}


def _normalize_name(name):
    if not name or pd.isna(name):
        return ""
    n = str(name).upper()
    n = _STRIP_RE.sub(" ", n)
    n = _SPACE_RE.sub(" ", n).strip()
    tokens = n.split()
    while tokens and tokens[-1] in _NAME_SUFFIXES:
        tokens.pop()
    return " ".join(tokens)


def _map_col(df_cols, candidates):
    cols_lower = {c.lower(): c for c in df_cols}
    for cand in candidates:
        if cand in df_cols:
            return cand
        if cand.lower() in cols_lower:
            return cols_lower[cand.lower()]
    return None


def _read_file(path, logger):
    suffix = path.suffix.lower()
    try:
        if suffix in (".xlsx", ".xls"):
            xl = pd.ExcelFile(path)
            best = pd.DataFrame()
            for sheet in xl.sheet_names:
                try:
                    df = pd.read_excel(xl, sheet_name=sheet, dtype=str, na_filter=False)
                    if len(df) > len(best):
                        best = df
                except Exception:
                    pass
            logger.info(f"  Read {len(best):,} rows from {path.name}")
            return best
        elif suffix == ".csv":
            for enc in ("utf-8", "latin-1", "utf-8-sig"):
                try:
                    df = pd.read_csv(path, dtype=str, na_filter=False, encoding=enc, low_memory=False)
                    logger.info(f"  Read {len(df):,} rows from {path.name}")
                    return df
                except UnicodeDecodeError:
                    continue
            raise ValueError(f"Could not decode {path.name}")
        else:
            logger.warning(f"  Unsupported: {path.name}")
            return pd.DataFrame()
    except Exception as e:
        logger.warning(f"  Failed to read {path.name}: {e}")
        return pd.DataFrame()


def _parse_df(df, source_file, logger):
    if df.empty:
        return pd.DataFrame(columns=CABILDEROS_COLUMNS)

    out = {}
    for out_col, candidates in COL_MAP.items():
        src = _map_col(df.columns.tolist(), candidates)
        out[out_col] = df[src].fillna("").astype(str) if src else ""

    result = pd.DataFrame(out)
    result["lobbyist_normalized"] = result["lobbyist_name"].apply(_normalize_name)
    result["client_normalized"] = result["client_name"].apply(_normalize_name)
    result["source_file"] = source_file

    for col in CABILDEROS_COLUMNS:
        if col not in result.columns:
            result[col] = ""

    result = result[result["client_name"].str.strip() != ""]
    logger.info(f"  → {len(result):,} cabildero records from {source_file}")
    return result[CABILDEROS_COLUMNS]


def _find_files(raw_dir, logger):
    folder = raw_dir / "Cabilderos"
    if not folder.exists():
        logger.warning(f"  Cabilderos folder not found: {folder}")
        return []
    files = [f for f in sorted(folder.iterdir())
             if f.suffix.lower() in (".csv", ".xlsx", ".xls") and not f.name.startswith("~")]
    logger.info(f"  Found {len(files)} Cabilderos file(s) in {folder}")
    return files


def _file_has_data(path):
    if not path.exists():
        return False
    try:
        return len(pd.read_csv(path, dtype=str, nrows=2)) > 0
    except Exception:
        return False


def run(root=None):
    return _run(root=root, force=False)


def _run(root=None, force=False):
    if root is None:
        root = PROJECT_ROOT
    out_path = root / "data" / "staging" / "processed" / "pr_cabilderos.csv"
    raw_dir = root / "data" / "raw"
    logger = setup_logging("ingest_cabilderos")
    logger.info("Starting Cabilderos (PR state lobbyists) ingestion...")

    if not force and _file_has_data(out_path):
        rows = len(pd.read_csv(out_path, dtype=str, low_memory=False))
        logger.info(f"  pr_cabilderos.csv exists ({rows:,} rows) — skipping.")
        return {"rows": rows, "path": str(out_path), "errors": []}

    files = _find_files(raw_dir, logger)
    if not files:
        logger.warning("  No Cabilderos files found. Place files in data/raw/Cabilderos/")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(columns=CABILDEROS_COLUMNS).to_csv(out_path, index=False, encoding="utf-8")
        return {"rows": 0, "path": str(out_path), "errors": ["No Cabilderos files found"]}

    all_dfs = []
    errors = []
    for f in files:
        logger.info(f"  Processing {f.name}...")
        df_raw = _read_file(f, logger)
        df_out = _parse_df(df_raw, f.name, logger)
        if not df_out.empty:
            all_dfs.append(df_out)
        else:
            errors.append(f"No records from {f.name}")

    if not all_dfs:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(columns=CABILDEROS_COLUMNS).to_csv(out_path, index=False, encoding="utf-8")
        return {"rows": 0, "path": str(out_path), "errors": errors or ["No data extracted"]}

    combined = pd.concat(all_dfs, ignore_index=True).drop_duplicates()

    out_path.parent.mkdir(parents=True, exist_ok=True)
    combined.to_csv(out_path, index=False, encoding="utf-8")

    logger.info("=" * 60)
    logger.info("CABILDEROS SUMMARY")
    logger.info("=" * 60)
    logger.info(f"  Total records:       {len(combined):,}")
    logger.info(f"  Unique lobbyists:    {combined['lobbyist_normalized'].nunique():,}")
    logger.info(f"  Unique clients:      {combined['client_normalized'].nunique():,}")

    return {"rows": len(combined), "path": str(out_path), "errors": errors}


def main():
    parser = argparse.ArgumentParser(description="Ingest PR Cabilderos lobbyist registry")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    result = _run(force=args.force)
    print(f"\nCabilderos ingestion complete: {result['rows']:,} records")
    return 1 if result["errors"] and result["rows"] == 0 else 0


if __name__ == "__main__":
    sys.exit(main())
