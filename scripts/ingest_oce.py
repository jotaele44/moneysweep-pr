"""
Ingest PR Oficina del Contralor Electoral (OCE) campaign-finance exports.

The Oficina del Contralor Electoral (OCE) is the PR agency that oversees
campaign-finance reporting at the *party committee* level — distinct from CEE
(donor-level filings handled by ingest_donaciones.py) and distinct from the
existing oficina_contralor source (the government-audit Contralor, a different
agency).

Place one or more CSV / Excel exports from:
  https://oce.pr.gov/

into  data/raw/OCE/

Output (column-aligned to pr_donaciones.csv so the NGO political-donation
crossref can consume both feeds uniformly):
  data/staging/processed/pr_oce_donations.csv

Usage:
  python3 scripts/ingest_oce.py
  python3 scripts/ingest_oce.py --force
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from scripts.config import PROJECT_ROOT, setup_logging

RAW_DIR_NAME = "data/raw/OCE"

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

# Column-name candidates per target field, tried in order (first match wins).
# OCE exports are largely Spanish; English fallbacks are included for tooling
# that exports with mixed headers.
COL_MAP = {
    "cycle": [
        "ciclo",
        "cycle",
        "anio_electoral",
        "año_electoral",
        "election_year",
    ],
    "donor_name": [
        "nombre_donante",
        "nombre donante",
        "donante",
        "donor_name",
        "contribuyente",
        "nombre_contribuyente",
        "nombre",
    ],
    "donor_city": [
        "ciudad",
        "ciudad_donante",
        "municipio",
        "city",
        "donor_city",
    ],
    "donor_zip_code": [
        "zip",
        "codigo_postal",
        "código_postal",
        "donor_zip",
        "donor_zip_code",
    ],
    "donor_employer": [
        "patrono",
        "empleador",
        "empleo",
        "employer",
        "donor_employer",
    ],
    "donor_occupation": [
        "ocupacion",
        "ocupación",
        "profesion",
        "profesión",
        "occupation",
        "donor_occupation",
    ],
    "amount": [
        "cantidad",
        "monto",
        "amount",
        "contribucion",
        "contribución",
        "donativo",
    ],
    "contribution_date": [
        "fecha",
        "fecha_donacion",
        "fecha_contribucion",
        "fecha_donación",
        "fecha_contribución",
        "date",
        "contribution_date",
    ],
    "candidate_or_committee": [
        "comite",
        "comité",
        "candidato",
        "candidato_comite",
        "candidato_comité",
        "candidate",
        "committee",
        "candidate_or_committee",
        "nombre_comite",
        "nombre_comité",
    ],
    "party": [
        "partido",
        "partido_politico",
        "partido_político",
        "party",
    ],
    "office_sought": [
        "cargo",
        "puesto",
        "posicion",
        "posición",
        "office",
        "office_sought",
    ],
    "election_type": [
        "tipo_eleccion",
        "tipo_elección",
        "tipo",
        "eleccion",
        "elección",
        "election_type",
    ],
    "report_type": [
        "tipo_informe",
        "informe",
        "tipo_reporte",
        "report_type",
        "report",
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
    donor = out_df["donor_name"].fillna("").astype(str).str.strip()
    out_df = out_df[(donor != "") & (donor.str.lower() != "nan")]
    return out_df[OUTPUT_COLUMNS]


def run(root: Path | None = None, force: bool = False) -> dict:
    if root is None:
        root = PROJECT_ROOT
    root = Path(root)
    raw_dir = root / RAW_DIR_NAME
    out_path = root / "data" / "staging" / "processed" / "pr_oce_donations.csv"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    logger = setup_logging("ingest_oce")

    if not force and out_path.exists():
        existing = pd.read_csv(out_path, dtype=str, low_memory=False)
        if len(existing) > 0:
            logger.info(f"  Cached — {len(existing):,} rows in {out_path.name}")
            return {"rows": len(existing), "path": str(out_path), "status": "CACHED"}

    if not raw_dir.exists():
        logger.info(f"  No OCE raw dir at {raw_dir} — skipping ingest")
        pd.DataFrame(columns=OUTPUT_COLUMNS).to_csv(out_path, index=False, encoding="utf-8")
        return {"rows": 0, "path": str(out_path), "status": "NO_FILES"}

    files = sorted(
        f
        for f in raw_dir.iterdir()
        if f.suffix.lower() in (".csv", ".xlsx", ".xls") and not f.name.startswith("~")
    )
    if not files:
        logger.info(f"  No files in {raw_dir} — skipping ingest")
        pd.DataFrame(columns=OUTPUT_COLUMNS).to_csv(out_path, index=False, encoding="utf-8")
        return {"rows": 0, "path": str(out_path), "status": "NO_FILES"}

    logger.info(f"  Found {len(files)} OCE export file(s) in {raw_dir}")
    frames = []
    for f in files:
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
        logger.warning("  No parseable OCE export files found")
        pd.DataFrame(columns=OUTPUT_COLUMNS).to_csv(out_path, index=False, encoding="utf-8")
        return {"rows": 0, "path": str(out_path), "status": "EMPTY"}

    combined = pd.concat(frames, ignore_index=True).drop_duplicates()
    combined.to_csv(out_path, index=False, encoding="utf-8")
    logger.info(f"  Written: {out_path.name} ({len(combined):,} rows)")
    return {"rows": len(combined), "path": str(out_path), "status": "OK"}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Ingest OCE campaign-finance CSV/Excel exports from data/raw/OCE/"
    )
    parser.add_argument("--force", action="store_true", help="Re-ingest even if output exists")
    args = parser.parse_args()
    result = run(force=args.force)
    print(f"\nOCE ingest: {result['rows']:,} rows — {result['status']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
