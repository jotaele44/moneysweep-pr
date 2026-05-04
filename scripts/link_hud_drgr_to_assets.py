"""
Link HUD DRGR activities to physical assets and municipalities.

Inputs:
  data/normalized/hud_drgr_activities.parquet
  data/staging/processed/pr_municipal_finance.csv  (if exists)
  data/staging/processed/pr_cor3_projects.csv      (if exists)

Output:
  data/linked/hud_drgr_asset_linkage.csv

Usage:
  python3 scripts/link_hud_drgr_to_assets.py
  python3 scripts/link_hud_drgr_to_assets.py --force
"""

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from scripts.config import PROJECT_ROOT, setup_logging

LINKED_DIR = PROJECT_ROOT / "data" / "linked"

ASSET_LINKAGE_COLUMNS = [
    "activity_id", "grant_number", "activity_name",
    "municipality", "municipality_matched",
    "county",
    "cor3_project_id", "cor3_total_approved",
    "municipal_finance_grade",
    "asset_type",
    "total_budget", "amount_drawn",
]

PR_MUNICIPALITIES = {
    "ADJUNTAS", "AGUADA", "AGUADILLA", "AGUAS BUENAS", "AIBONITO",
    "ANASCO", "ARECIBO", "ARROYO", "BARCELONETA", "BARRANQUITAS",
    "BAYAMON", "CABO ROJO", "CAGUAS", "CAMUY", "CANOVANAS",
    "CAROLINA", "CATANO", "CAYEY", "CEIBA", "CIALES",
    "CIDRA", "COAMO", "COMERIO", "COROZAL", "CULEBRA",
    "DORADO", "FAJARDO", "FLORIDA", "GUANICA", "GUAYAMA",
    "GUAYANILLA", "GUAYNABO", "GURABO", "HATILLO", "HORMIGUEROS",
    "HUMACAO", "ISABELA", "JAYUYA", "JUANA DIAZ", "JUNCOS",
    "LAJAS", "LARES", "LAS MARIAS", "LAS PIEDRAS", "LOIZA",
    "LUQUILLO", "MANATI", "MARICAO", "MAUNABO", "MAYAGUEZ",
    "MOCA", "MOROVIS", "NAGUABO", "NARANJITO", "OROCOVIS",
    "PATILLAS", "PENUELAS", "PONCE", "QUEBRADILLAS", "RINCON",
    "RIO GRANDE", "SABANA GRANDE", "SALINAS", "SAN GERMAN", "SAN JUAN",
    "SAN LORENZO", "SAN SEBASTIAN", "SANTA ISABEL", "TOA ALTA", "TOA BAJA",
    "TRUJILLO ALTO", "UTUADO", "VEGA ALTA", "VEGA BAJA", "VIEQUES",
    "VILLALBA", "YABUCOA", "YAUCO",
}

ASSET_TYPE_KEYWORDS = {
    "housing":        ["housing", "home", "residential", "homeowner", "rental", "dwelling", "lihtc"],
    "infrastructure": ["infrastructure", "road", "water", "sewer", "electric", "power", "grid", "utility", "bridge", "drainage"],
    "economic":       ["economic", "business", "commercial", "industry", "job", "employment", "workforce"],
    "planning":       ["planning", "design", "study", "assessment", "management", "administration"],
}

_ACCENTS = str.maketrans("áéíóúàèìòùâêîôûäëïöüñÁÉÍÓÚÀÈÌÒÙÂÊÎÔÛÄËÏÖÜÑ",
                          "aeiouaeiouaeiouaeiounAEIOUAEIOUAEIOUAEIOUN")


def _clean_muni(name):
    if not name or pd.isna(name):
        return ""
    return re.sub(r"\s+", " ", str(name).upper().translate(_ACCENTS)).strip()


def _match_municipality(raw):
    cleaned = _clean_muni(raw)
    if cleaned in PR_MUNICIPALITIES:
        return cleaned
    for muni in PR_MUNICIPALITIES:
        if muni in cleaned or cleaned in muni:
            return muni
    return ""


def _classify_asset_type(name, activity_type):
    combined = (str(name) + " " + str(activity_type)).lower()
    for asset_type, keywords in ASSET_TYPE_KEYWORDS.items():
        if any(kw in combined for kw in keywords):
            return asset_type
    return "other"


def run(root=None, force=False):
    root = Path(root or PROJECT_ROOT)
    LINKED_DIR.mkdir(parents=True, exist_ok=True)
    out_path = root / "data" / "linked" / "hud_drgr_asset_linkage.csv"
    logger = setup_logging("link_hud_drgr_to_assets")

    if out_path.exists() and not force:
        rows = len(pd.read_csv(out_path, dtype=str, nrows=10000))
        logger.info(f"  hud_drgr_asset_linkage.csv exists ({rows:,} rows) — skipping.")
        return {"linkage_rows": rows, "municipalities_matched": 0, "status": "CACHED"}

    norm_dir = root / "data" / "normalized"
    proc_dir = root / "data" / "staging" / "processed"

    # Load activities
    activity_path = norm_dir / "hud_drgr_activities.parquet"
    if not activity_path.exists():
        logger.warning("  No hud_drgr_activities.parquet — writing empty linkage")
        pd.DataFrame(columns=ASSET_LINKAGE_COLUMNS).to_csv(out_path, index=False)
        return {"linkage_rows": 0, "municipalities_matched": 0, "status": "EMPTY"}

    try:
        df_activities = pd.read_parquet(activity_path, engine="pyarrow")
        logger.info(f"  Loaded {len(df_activities):,} activities")
    except Exception as e:
        logger.warning(f"  Failed to read activities: {e}")
        df_activities = pd.DataFrame()

    # Load supplementary data
    df_municipal = pd.DataFrame()
    muni_path = proc_dir / "pr_municipal_finance.csv"
    if muni_path.exists():
        try:
            df_municipal = pd.read_csv(muni_path, dtype=str, low_memory=False)
            logger.info(f"  Loaded {len(df_municipal):,} municipal finance rows")
        except Exception:
            pass

    df_cor3 = pd.DataFrame()
    cor3_path = proc_dir / "pr_cor3_projects.csv"
    if cor3_path.exists():
        try:
            df_cor3 = pd.read_csv(cor3_path, dtype=str, low_memory=False)
            logger.info(f"  Loaded {len(df_cor3):,} COR3 projects")
        except Exception:
            pass

    # Build municipal finance lookup
    muni_grade_lookup = {}
    if not df_municipal.empty:
        for col in ["municipality", "muni_name", "name"]:
            if col in df_municipal.columns:
                for _, r in df_municipal.iterrows():
                    key = _clean_muni(r.get(col, ""))
                    if key:
                        muni_grade_lookup[key] = str(r.get("abre_grade", r.get("grade", ""))).strip()
                break

    # Build COR3 lookup by municipality
    cor3_muni_lookup = {}
    if not df_cor3.empty and "municipality" in df_cor3.columns:
        for _, r in df_cor3.iterrows():
            key = _clean_muni(r.get("municipality", ""))
            if key and key not in cor3_muni_lookup:
                cor3_muni_lookup[key] = r

    rows = []
    municipalities_matched = set()

    if not df_activities.empty:
        for _, act in df_activities.iterrows():
            raw_muni = act.get("municipality", act.get("county", ""))
            muni_matched = _match_municipality(raw_muni)
            if muni_matched:
                municipalities_matched.add(muni_matched)

            cor3_row = cor3_muni_lookup.get(muni_matched, {})
            grade = muni_grade_lookup.get(muni_matched, "")
            asset_type = _classify_asset_type(
                act.get("activity_name", ""), act.get("activity_type", "")
            )

            rows.append({
                "activity_id":          act.get("activity_id", ""),
                "grant_number":         act.get("grant_number", ""),
                "activity_name":        act.get("activity_name", ""),
                "municipality":         str(raw_muni).strip(),
                "municipality_matched": muni_matched,
                "county":               act.get("county", ""),
                "cor3_project_id":      str(cor3_row.get("project_id", "")) if cor3_row else "",
                "cor3_total_approved":  str(cor3_row.get("total_approved", "")) if cor3_row else "",
                "municipal_finance_grade": grade,
                "asset_type":           asset_type,
                "total_budget":         act.get("total_budget", ""),
                "amount_drawn":         act.get("amount_drawn", ""),
            })

    df_out = pd.DataFrame(rows, columns=ASSET_LINKAGE_COLUMNS) if rows else pd.DataFrame(columns=ASSET_LINKAGE_COLUMNS)
    df_out.to_csv(out_path, index=False, encoding="utf-8")

    logger.info(f"  Asset linkage: {len(df_out):,} rows, {len(municipalities_matched)} unique municipalities matched")
    return {"linkage_rows": len(df_out), "municipalities_matched": len(municipalities_matched), "status": "OK"}


def main():
    parser = argparse.ArgumentParser(description="Link HUD DRGR activities to assets/municipalities")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    result = run(force=args.force)
    print(f"\nHUD DRGR asset linkage: {result['linkage_rows']:,} rows, "
          f"{result['municipalities_matched']} municipalities matched")
    return 0


if __name__ == "__main__":
    sys.exit(main())
