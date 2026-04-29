"""
Ingest PRASA (Puerto Rico Aqueduct and Sewer Authority) contract data.

PRASA is a public corporation that manages PR's water and sewer infrastructure.
It receives both PR government operating funds and federal FEMA/EPA infrastructure
grants. PRASA contract vendors who also receive direct federal awards = dual-channel
recipients. PRASA procurement is also a major target for the same contractors that
dominate post-Maria reconstruction.

Input:
  data/raw/PRASA/ — CSV or Excel files from PRASA procurement records

Output:
  data/staging/processed/pr_prasa_contracts.csv

Usage:
  python3 scripts/ingest_prasa.py
  python3 scripts/ingest_prasa.py --force
"""

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from scripts.config import PROJECT_ROOT, setup_logging

PRASA_COLUMNS = [
    "contract_id", "vendor_name", "vendor_normalized",
    "contract_type", "contract_value",
    "award_date", "start_date", "end_date", "status",
    "description", "municipality", "source_file",
]

COL_MAP = {
    "contract_id": [
        "Contract ID", "Contrato", "Número de Contrato", "Contract Number",
        "ID", "Número", "PIID", "contrato_id",
    ],
    "vendor_name": [
        "Vendor Name", "Contratista", "Suplidor", "Contractor", "Nombre",
        "Business Name", "Proveedor", "Company", "vendor_name",
    ],
    "contract_type": [
        "Type", "Tipo", "Contract Type", "Tipo de Contrato",
        "Award Type", "tipo",
    ],
    "contract_value": [
        "Amount", "Monto", "Contract Value", "Total", "Valor",
        "Obligated Amount", "Total Contract Value", "monto",
    ],
    "award_date": [
        "Award Date", "Fecha de Adjudicación", "Fecha", "Date",
        "Contract Date", "fecha_adjudicacion",
    ],
    "start_date": [
        "Start Date", "Fecha de Inicio", "Begin Date", "Inicio",
        "fecha_inicio",
    ],
    "end_date": [
        "End Date", "Fecha de Terminación", "Expiration Date", "Fin",
        "Termination Date", "fecha_fin",
    ],
    "status": [
        "Status", "Estado", "Estatus", "Active", "Activo",
        "Contract Status", "estado",
    ],
    "description": [
        "Description", "Descripción", "Scope", "Purpose",
        "Description of Work", "descripcion",
    ],
    "municipality": [
        "Municipality", "Municipio", "Location", "Lugar",
        "municipio",
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
        return pd.DataFrame(columns=PRASA_COLUMNS)

    out = {}
    for out_col, candidates in COL_MAP.items():
        src = _map_col(df.columns.tolist(), candidates)
        out[out_col] = df[src].fillna("").astype(str) if src else ""

    result = pd.DataFrame(out)
    result["vendor_normalized"] = result["vendor_name"].apply(_normalize_name)
    result["source_file"] = source_file

    for col in PRASA_COLUMNS:
        if col not in result.columns:
            result[col] = ""

    result = result[result["vendor_name"].str.strip() != ""]
    logger.info(f"  → {len(result):,} PRASA contract records from {source_file}")
    return result[PRASA_COLUMNS]


def _find_files(raw_dir, logger):
    folder = raw_dir / "PRASA"
    if not folder.exists():
        logger.warning(f"  PRASA folder not found: {folder}")
        return []
    files = [f for f in sorted(folder.iterdir())
             if f.suffix.lower() in (".csv", ".xlsx", ".xls") and not f.name.startswith("~")]
    logger.info(f"  Found {len(files)} PRASA file(s) in {folder}")
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
    out_path = root / "data" / "staging" / "processed" / "pr_prasa_contracts.csv"
    raw_dir = root / "data" / "raw"
    logger = setup_logging("ingest_prasa")
    logger.info("Starting PRASA contract data ingestion...")

    if not force and _file_has_data(out_path):
        rows = len(pd.read_csv(out_path, dtype=str, low_memory=False))
        logger.info(f"  pr_prasa_contracts.csv exists ({rows:,} rows) — skipping.")
        return {"rows": rows, "path": str(out_path), "errors": []}

    files = _find_files(raw_dir, logger)
    if not files:
        logger.warning("  No PRASA files found. Place files in data/raw/PRASA/")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(columns=PRASA_COLUMNS).to_csv(out_path, index=False, encoding="utf-8")
        return {"rows": 0, "path": str(out_path), "errors": ["No PRASA files found"]}

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
        pd.DataFrame(columns=PRASA_COLUMNS).to_csv(out_path, index=False, encoding="utf-8")
        return {"rows": 0, "path": str(out_path), "errors": errors or ["No data extracted"]}

    combined = pd.concat(all_dfs, ignore_index=True).drop_duplicates(
        subset=["vendor_normalized", "contract_id"]
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    combined.to_csv(out_path, index=False, encoding="utf-8")

    total_val = pd.to_numeric(combined["contract_value"], errors="coerce").fillna(0).sum()
    logger.info("=" * 60)
    logger.info("PRASA CONTRACTS SUMMARY")
    logger.info("=" * 60)
    logger.info(f"  Total contracts:     {len(combined):,}")
    logger.info(f"  Unique vendors:      {combined['vendor_normalized'].nunique():,}")
    logger.info(f"  Total contract value: ${total_val:,.0f}")

    return {"rows": len(combined), "path": str(out_path), "errors": errors}


def main():
    parser = argparse.ArgumentParser(description="Ingest PRASA contract data")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    result = _run(force=args.force)
    print(f"\nPRASA ingestion complete: {result['rows']:,} contract records")
    return 1 if result["errors"] and result["rows"] == 0 else 0


if __name__ == "__main__":
    sys.exit(main())
