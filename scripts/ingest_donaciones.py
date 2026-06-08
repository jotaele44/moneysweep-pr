"""
Ingest PR State Election Commission (CEE/CEEPUR) donation data.

Place one or more CSV files exported from:
  https://www.ceepur.org/

into  data/raw/Donaciones/

The CEE website produces a CSV with Spanish-language column headers. The mapper
is flexible to handle different export formats across election cycles.

Output:
  data/staging/processed/pr_donaciones.csv

Usage:
  python3 scripts/ingest_donaciones.py
  python3 scripts/ingest_donaciones.py --force
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from scripts.config import PROJECT_ROOT, setup_logging

RAW_DIR_NAME = "data/raw/Donaciones"

OUTPUT_COLUMNS = [
    "cycle",
    "donor_name",
    "donor_city",
    "donor_zip_code",
    "donor_employer",
    "donor_occupation",
    "amount",
    "contribution_date",
    "candidate_or_committee",
    "party",
    "office_sought",
    "election_type",
    "report_type",
    "source_file",
]

# Column name candidates for each output field (tried in order, first match wins)
COL_MAP = {
    "cycle": [
        "ciclo",
        "cycle",
        "año_eleccion",
        "ano_eleccion",
        "election_year",
        "año electoral",
        "anio_electoral",
    ],
    "donor_name": [
        "nombre_donante",
        "nombre donante",
        "donante",
        "donor_name",
        "nombre_contribuyente",
        "contribuyente",
        "nombre",
    ],
    "donor_city": [
        "ciudad_donante",
        "ciudad",
        "city",
        "donor_city",
        "municipio",
    ],
    "donor_zip_code": [
        "zip_donante",
        "zip",
        "codigo_postal",
        "postal_code",
        "donor_zip",
    ],
    "donor_employer": [
        "patrono",
        "empleador",
        "employer",
        "donor_employer",
        "empleo",
    ],
    "donor_occupation": [
        "ocupacion",
        "ocupación",
        "occupation",
        "donor_occupation",
        "profesion",
    ],
    "amount": [
        "cantidad",
        "monto",
        "amount",
        "contribucion",
        "contribution_amount",
        "donativo",
        "donación",
    ],
    "contribution_date": [
        "fecha_donacion",
        "fecha donacion",
        "fecha",
        "date",
        "contribution_date",
        "fecha_contribucion",
    ],
    "candidate_or_committee": [
        "candidato_comite",
        "candidato",
        "comite",
        "candidate",
        "committee",
        "candidato_o_comite",
        "nombre_comite",
    ],
    "party": [
        "partido",
        "party",
        "partido_politico",
    ],
    "office_sought": [
        "cargo",
        "puesto",
        "office",
        "office_sought",
        "posicion",
    ],
    "election_type": [
        "tipo_eleccion",
        "tipo eleccion",
        "election_type",
        "tipo",
        "eleccion",
    ],
    "report_type": [
        "tipo_informe",
        "informe",
        "report_type",
        "report",
        "tipo_reporte",
    ],
}


def _map_col(df: pd.DataFrame, candidates: list[str]):
    df_lower = {c.lower().strip(): c for c in df.columns}
    for cand in candidates:
        actual = df_lower.get(cand.lower().strip())
        if actual is not None:
            return actual
    return None


def _parse_df(df: pd.DataFrame, source_file: str) -> pd.DataFrame:
    out = {}
    for target, candidates in COL_MAP.items():
        src_col = _map_col(df, candidates)
        out[target] = df[src_col].astype(str).str.strip() if src_col is not None else ""

    out_df = pd.DataFrame(out)
    out_df["source_file"] = source_file

    for col in OUTPUT_COLUMNS:
        if col not in out_df.columns:
            out_df[col] = ""

    # Filter out rows with no donor name
    out_df = out_df[out_df["donor_name"].str.strip() != ""]
    return out_df[OUTPUT_COLUMNS]


def run(root: Path = None, force: bool = False) -> dict:
    if root is None:
        root = PROJECT_ROOT
    root = Path(root)
    raw_dir = root / RAW_DIR_NAME
    out_path = root / "data" / "staging" / "processed" / "pr_donaciones.csv"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    logger = setup_logging("ingest_donaciones")

    if not force and out_path.exists():
        existing = pd.read_csv(out_path, dtype=str, low_memory=False)
        if len(existing) > 0:
            logger.info(f"  Cached — {len(existing):,} rows in {out_path.name}")
            return {"rows": len(existing), "path": str(out_path), "status": "CACHED"}

    if not raw_dir.exists():
        logger.info(f"  No Donaciones raw dir at {raw_dir} — skipping ingest")
        pd.DataFrame(columns=OUTPUT_COLUMNS).to_csv(out_path, index=False, encoding="utf-8")
        return {"rows": 0, "path": str(out_path), "status": "NO_FILES"}

    csv_files = sorted(
        f
        for f in raw_dir.iterdir()
        if f.suffix.lower() in (".csv", ".xlsx", ".xls") and not f.name.startswith("~")
    )
    if not csv_files:
        logger.info(f"  No files in {raw_dir} — skipping ingest")
        pd.DataFrame(columns=OUTPUT_COLUMNS).to_csv(out_path, index=False, encoding="utf-8")
        return {"rows": 0, "path": str(out_path), "status": "NO_FILES"}

    logger.info(f"  Found {len(csv_files)} CEE export file(s) in {raw_dir}")
    frames = []
    for f in csv_files:
        logger.info(f"  Reading {f.name}...")
        try:
            if f.suffix.lower() == ".csv":
                df = pd.read_csv(f, dtype=str, low_memory=False, encoding="utf-8")
            else:
                df = pd.read_excel(f, dtype=str)
            parsed = _parse_df(df, f.name)
            logger.info(f"    → {len(parsed):,} rows after mapping")
            frames.append(parsed)
        except Exception as e:
            logger.warning(f"  Could not parse {f.name}: {e}")

    if not frames:
        logger.warning("  No parseable CEE export files found")
        pd.DataFrame(columns=OUTPUT_COLUMNS).to_csv(out_path, index=False, encoding="utf-8")
        return {"rows": 0, "path": str(out_path), "status": "EMPTY"}

    combined = pd.concat(frames, ignore_index=True).drop_duplicates()
    combined.to_csv(out_path, index=False, encoding="utf-8")
    logger.info(f"  Written: {out_path.name} ({len(combined):,} rows)")
    return {"rows": len(combined), "path": str(out_path), "status": "OK"}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Ingest CEE/CEEPUR donation CSV exports from data/raw/Donaciones/"
    )
    parser.add_argument("--force", action="store_true", help="Re-ingest even if output exists")
    args = parser.parse_args()
    result = run(force=args.force)
    print(f"\nDonaciones ingest: {result['rows']:,} rows — {result['status']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
