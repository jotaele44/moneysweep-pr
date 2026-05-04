"""
Ingest PR Active Contractor Listing from the PR government registry.

The PR government maintains a list of vendors and contractors registered
and cleared to receive PR government contracts. Cross-referencing this list
with federal award recipients identifies entities embedded in both state
and federal procurement — systemically important vendors.

Input:
  data/raw/Active Contractor Listing/ — CSV or Excel files

Output:
  data/staging/processed/pr_active_contractors.csv

Usage:
  python3 scripts/ingest_active_contractors.py
  python3 scripts/ingest_active_contractors.py --force
"""

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from scripts.config import PROJECT_ROOT, setup_logging

CONTRACTOR_COLUMNS = [
    "entity_name", "entity_normalized",
    "registration_id", "registration_date", "expiry_date",
    "contractor_type", "naics_code", "municipality",
    "status", "source_file",
]

COL_MAP = {
    "entity_name": [
        "Nombre", "Name", "Vendor Name", "Contractor Name", "Business Name",
        "Nombre del Suplidor", "Suplidor", "Empresa", "Company",
        "nombre", "Razón Social",
    ],
    "registration_id": [
        "ID", "Registro", "Registration Number", "Número de Registro",
        "Vendor ID", "CFSE", "AS", "Registro Único",
    ],
    "registration_date": [
        "Fecha de Registro", "Registration Date", "Fecha",
        "Start Date", "fecha_registro",
    ],
    "expiry_date": [
        "Fecha de Expiración", "Expiry Date", "Expiration Date",
        "End Date", "fecha_expiracion",
    ],
    "contractor_type": [
        "Tipo", "Type", "Categoría", "Category", "Clasificación",
        "Contractor Type", "tipo",
    ],
    "naics_code": [
        "NAICS", "NAICS Code", "Código NAICS", "Industry Code",
        "naics",
    ],
    "municipality": [
        "Municipio", "Municipality", "Ciudad", "City", "Location",
        "municipio",
    ],
    "status": [
        "Estado", "Status", "Estatus", "Active", "Activo",
        "estado",
    ],
}

_STRIP_RE = re.compile(r"[^\w\s]")
_SPACE_RE = re.compile(r"\s+")
_NAME_SUFFIXES = {
    "INC", "LLC", "CORP", "LTD", "CO", "LP", "LLP",
    "COMPANY", "CORPORATION", "INCORPORATED", "LIMITED",
    "CSP", "SE",
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
        logger.warning(f"  Unsupported: {path.name}")
        return pd.DataFrame()
    except Exception as e:
        logger.warning(f"  Failed to read {path.name}: {e}")
        return pd.DataFrame()


def _parse_df(df, source_file, logger):
    if df.empty:
        return pd.DataFrame(columns=CONTRACTOR_COLUMNS)

    out = {}
    for out_col, candidates in COL_MAP.items():
        src = _map_col(df.columns.tolist(), candidates)
        out[out_col] = df[src].fillna("").astype(str) if src else ""

    result = pd.DataFrame(out)
    result["entity_normalized"] = result["entity_name"].apply(_normalize_name)
    result["source_file"] = source_file

    for col in CONTRACTOR_COLUMNS:
        if col not in result.columns:
            result[col] = ""

    result = result[result["entity_name"].str.strip() != ""]
    logger.info(f"  → {len(result):,} contractor records from {source_file}")
    return result[CONTRACTOR_COLUMNS]


def _find_files(raw_dir, logger):
    folder = raw_dir / "Active Contractor Listing"
    if not folder.exists():
        logger.warning(f"  Active Contractor Listing folder not found: {folder}")
        return []
    files = [f for f in sorted(folder.iterdir())
             if f.suffix.lower() in (".csv", ".xlsx", ".xls") and not f.name.startswith("~")]
    logger.info(f"  Found {len(files)} Active Contractor file(s) in {folder}")
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
    out_path = root / "data" / "staging" / "processed" / "pr_active_contractors.csv"
    raw_dir = root / "data" / "raw"
    logger = setup_logging("ingest_active_contractors")
    logger.info("Starting PR Active Contractor Listing ingestion...")

    if not force and _file_has_data(out_path):
        rows = len(pd.read_csv(out_path, dtype=str, low_memory=False))
        logger.info(f"  pr_active_contractors.csv exists ({rows:,} rows) — skipping.")
        return {"rows": rows, "path": str(out_path), "errors": []}

    files = _find_files(raw_dir, logger)
    if not files:
        logger.warning("  No Active Contractor files found. Place files in 'data/raw/Active Contractor Listing/'")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(columns=CONTRACTOR_COLUMNS).to_csv(out_path, index=False, encoding="utf-8")
        return {"rows": 0, "path": str(out_path), "errors": ["No Active Contractor files found"]}

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
        pd.DataFrame(columns=CONTRACTOR_COLUMNS).to_csv(out_path, index=False, encoding="utf-8")
        return {"rows": 0, "path": str(out_path), "errors": errors or ["No data extracted"]}

    combined = pd.concat(all_dfs, ignore_index=True).drop_duplicates(
        subset=["entity_normalized", "registration_id"]
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    combined.to_csv(out_path, index=False, encoding="utf-8")

    active = (combined["status"].str.lower().str.contains("activ", na=False)).sum()
    logger.info("=" * 60)
    logger.info("ACTIVE CONTRACTORS SUMMARY")
    logger.info("=" * 60)
    logger.info(f"  Total records:       {len(combined):,}")
    logger.info(f"  Unique entities:     {combined['entity_normalized'].nunique():,}")
    logger.info(f"  Active status:       {active:,}")

    return {"rows": len(combined), "path": str(out_path), "errors": errors}


def main():
    parser = argparse.ArgumentParser(description="Ingest PR Active Contractor Listing")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    result = _run(force=args.force)
    print(f"\nActive Contractors ingestion complete: {result['rows']:,} records")
    return 1 if result["errors"] and result["rows"] == 0 else 0


if __name__ == "__main__":
    sys.exit(main())
