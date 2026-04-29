"""
Ingest PR Oficina del Contralor (Comptroller's Office) audit and contract data.

The Contralor issues audit reports and certifications for PR government entities
and contractors. A federal award recipient with an open Contralor finding =
compliance risk signal. Certifications show which entities are legally cleared
to receive PR government contracts.

Input:
  data/raw/Oficina del Contralor/ — CSV or Excel files from contralor.pr.gov

Output:
  data/staging/processed/pr_contralor_audits.csv

Usage:
  python3 scripts/ingest_contralor.py
  python3 scripts/ingest_contralor.py --force
"""

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from scripts.config import PROJECT_ROOT, setup_logging

CONTRALOR_COLUMNS = [
    "entity_name", "entity_normalized",
    "audit_id", "audit_type",
    "audit_year", "audit_date",
    "finding_count", "finding_type",
    "contract_amount", "municipality",
    "recommendation", "status",
    "source_file",
]

COL_MAP = {
    "entity_name": [
        "Entidad", "Entity", "Nombre", "Agencia", "Agency",
        "Nombre de la Entidad", "Organization", "nombre_entidad",
        "Municipio", "Municipality", "Corporación", "Corporation",
    ],
    "audit_id": [
        "Número de Informe", "Report Number", "Informe", "Audit ID",
        "Número", "numero_informe", "ID", "Referencia",
    ],
    "audit_type": [
        "Tipo de Informe", "Report Type", "Tipo", "Audit Type",
        "Clasificación", "tipo_informe",
    ],
    "audit_year": [
        "Año", "Year", "Fiscal Year", "Año Fiscal", "anio",
        "Periodo", "Period",
    ],
    "audit_date": [
        "Fecha", "Date", "Fecha del Informe", "Report Date",
        "fecha_informe", "Issue Date",
    ],
    "finding_count": [
        "Hallazgos", "Findings", "Número de Hallazgos", "Finding Count",
        "hallazgos", "Num Findings",
    ],
    "finding_type": [
        "Tipo de Hallazgo", "Finding Type", "Categoría", "Category",
        "tipo_hallazgo",
    ],
    "contract_amount": [
        "Monto", "Amount", "Valor", "Contract Value", "Cantidad",
        "Total", "monto",
    ],
    "municipality": [
        "Municipio", "Municipality", "Pueblo", "Ciudad",
        "municipio",
    ],
    "recommendation": [
        "Recomendación", "Recommendation", "Acción Correctiva",
        "Corrective Action", "recomendacion",
    ],
    "status": [
        "Estado", "Status", "Estatus", "Disposition",
        "estado",
    ],
}

_STRIP_RE = re.compile(r"[^\w\s]")
_SPACE_RE = re.compile(r"\s+")
_NAME_SUFFIXES = {
    "INC", "LLC", "CORP", "LTD", "CO", "LP", "DE", "PR",
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
        logger.warning(f"  Unsupported or unreadable: {path.name}")
        return pd.DataFrame()
    except Exception as e:
        logger.warning(f"  Failed to read {path.name}: {e}")
        return pd.DataFrame()


def _parse_df(df, source_file, logger):
    if df.empty:
        return pd.DataFrame(columns=CONTRALOR_COLUMNS)

    out = {}
    for out_col, candidates in COL_MAP.items():
        src = _map_col(df.columns.tolist(), candidates)
        out[out_col] = df[src].fillna("").astype(str) if src else ""

    result = pd.DataFrame(out)
    result["entity_normalized"] = result["entity_name"].apply(_normalize_name)
    result["source_file"] = source_file

    for col in CONTRALOR_COLUMNS:
        if col not in result.columns:
            result[col] = ""

    result = result[result["entity_name"].str.strip() != ""]
    logger.info(f"  → {len(result):,} audit records from {source_file}")
    return result[CONTRALOR_COLUMNS]


def _find_files(raw_dir, logger):
    folder = raw_dir / "Oficina del Contralor"
    if not folder.exists():
        logger.warning(f"  Contralor folder not found: {folder}")
        return []
    files = [f for f in sorted(folder.iterdir())
             if f.suffix.lower() in (".csv", ".xlsx", ".xls") and not f.name.startswith("~")]
    logger.info(f"  Found {len(files)} Contralor file(s) in {folder}")
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
    out_path = root / "data" / "staging" / "processed" / "pr_contralor_audits.csv"
    raw_dir = root / "data" / "raw"
    logger = setup_logging("ingest_contralor")
    logger.info("Starting Oficina del Contralor data ingestion...")

    if not force and _file_has_data(out_path):
        rows = len(pd.read_csv(out_path, dtype=str, low_memory=False))
        logger.info(f"  pr_contralor_audits.csv exists ({rows:,} rows) — skipping.")
        return {"rows": rows, "path": str(out_path), "errors": []}

    files = _find_files(raw_dir, logger)
    if not files:
        logger.warning("  No Contralor files found. Place files in data/raw/Oficina del Contralor/")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(columns=CONTRALOR_COLUMNS).to_csv(out_path, index=False, encoding="utf-8")
        return {"rows": 0, "path": str(out_path), "errors": ["No Contralor files found"]}

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
        pd.DataFrame(columns=CONTRALOR_COLUMNS).to_csv(out_path, index=False, encoding="utf-8")
        return {"rows": 0, "path": str(out_path), "errors": errors or ["No data extracted"]}

    combined = pd.concat(all_dfs, ignore_index=True).drop_duplicates()

    out_path.parent.mkdir(parents=True, exist_ok=True)
    combined.to_csv(out_path, index=False, encoding="utf-8")

    open_count = (combined["status"].str.lower().str.contains("open|abierto", na=False)).sum()
    logger.info("=" * 60)
    logger.info("CONTRALOR SUMMARY")
    logger.info("=" * 60)
    logger.info(f"  Total audit records:  {len(combined):,}")
    logger.info(f"  Unique entities:      {combined['entity_normalized'].nunique():,}")
    logger.info(f"  Open findings:        {open_count:,}")

    return {"rows": len(combined), "path": str(out_path), "errors": errors}


def main():
    parser = argparse.ArgumentParser(description="Ingest PR Contralor audit data")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    result = _run(force=args.force)
    print(f"\nContralor ingestion complete: {result['rows']:,} audit records")
    return 1 if result["errors"] and result["rows"] == 0 else 0


if __name__ == "__main__":
    sys.exit(main())
