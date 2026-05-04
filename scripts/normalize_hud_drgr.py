"""
Normalize and reconcile HUD DRGR data from public downloads and local exports.

Inputs:
  data/normalized/hud_drgr_grants.parquet       (from download_hud_drgr_public)
  data/normalized/hud_drgr_activities.parquet    (from ingest_hud_drgr_exports)
  data/normalized/hud_drgr_drawdowns.parquet     (from ingest_hud_drgr_exports)
  data/normalized/hud_drgr_appropriations.parquet (from ingest_hud_drgr_exports)

Outputs:
  data/normalized/hud_drgr_projects.parquet
  data/normalized/hud_drgr_responsible_orgs_resolved.parquet

Usage:
  python3 scripts/normalize_hud_drgr.py
  python3 scripts/normalize_hud_drgr.py --force
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from scripts.build_unified_master import _normalize_name
from scripts.parquet_utils import pq_read, pq_write
from scripts.config import PROJECT_ROOT, setup_logging

NORMALIZED_DIR = PROJECT_ROOT / "data" / "normalized"

PROJECT_COLUMNS = [
    "grant_number", "grantee_name", "grantee_normalized",
    "program_type", "disaster_number",
    "grant_amount", "amount_drawn", "amount_remaining",
    "disbursement_rate",
    "activity_count", "completed_activity_count",
    "source_system",
]

ORG_COLUMNS = [
    "responsible_org", "responsible_org_normalized",
    "grant_number_list",
    "activity_count", "total_budget_managed",
    "total_drawn",
]


def _load(path, logger):
    if not path.exists():
        logger.warning(f"  Missing: {path.name}")
        return pd.DataFrame()
    try:
        df = pq_read(path)
        logger.info(f"  Loaded {len(df):,} rows from {path.name}")
        return df
    except Exception as e:
        logger.warning(f"  Failed to read {path.name}: {e}")
        return pd.DataFrame()


def _to_num(series):
    return pd.to_numeric(series, errors="coerce").fillna(0)


def _build_projects(df_grants, df_appropriations, df_activities, logger):
    """Merge grants and appropriations into project-level summary."""
    rows = []

    # Combine grants from public download and appropriations from exports
    combined_grants = []
    if not df_grants.empty:
        combined_grants.append(df_grants)
    if not df_appropriations.empty:
        # Map appropriations to grant schema
        appr = df_appropriations.copy()
        appr_mapped = pd.DataFrame({
            "grant_number":     appr.get("grant_number", ""),
            "grantee_name":     appr.get("grantee_name", ""),
            "grantee_normalized": appr.get("grantee_normalized", appr.get("grantee_name", pd.Series(dtype=str)).apply(_normalize_name)),
            "disaster_number":  "",
            "appropriation_year": appr.get("appropriation_year", ""),
            "grant_amount":     _to_num(appr.get("appropriation_amount", pd.Series(dtype=float))),
            "program_type":     appr.get("program_type", ""),
            "cfda_number":      appr.get("cfda_number", ""),
        })
        combined_grants.append(appr_mapped)

    if not combined_grants:
        logger.warning("  No grant/appropriation data — projects output will be empty")
        return pd.DataFrame(columns=PROJECT_COLUMNS)

    all_grants = pd.concat(combined_grants, ignore_index=True)

    # Deduplicate by grant_number
    if "grant_number" in all_grants.columns:
        all_grants = all_grants.drop_duplicates(subset=["grant_number"], keep="last")

    # Compute activity counts per grant
    activity_counts = {}
    completed_counts = {}
    drawn_per_grant = {}
    if not df_activities.empty and "grant_number" in df_activities.columns:
        for gn, grp in df_activities.groupby("grant_number"):
            activity_counts[str(gn)] = len(grp)
            completed_counts[str(gn)] = int((grp.get("status", pd.Series(dtype=str)).str.upper() == "COMPLETED").sum())
            drawn_per_grant[str(gn)] = _to_num(grp.get("amount_drawn", pd.Series(dtype=float))).sum()

    for _, r in all_grants.iterrows():
        gn = str(r.get("grant_number", "")).strip()
        grant_amt = float(_to_num(pd.Series([r.get("grant_amount", 0)])).iloc[0])
        amount_drawn = drawn_per_grant.get(gn, float(_to_num(pd.Series([r.get("amount_drawn", 0)])).iloc[0]))
        amount_remaining = grant_amt - amount_drawn
        disbursement_rate = round(amount_drawn / grant_amt, 4) if grant_amt > 0 else 0.0

        grantee = str(r.get("grantee_name", "")).strip()
        rows.append({
            "grant_number":            gn,
            "grantee_name":            grantee,
            "grantee_normalized":      _normalize_name(grantee),
            "program_type":            str(r.get("program_type", r.get("cfda_number", ""))).strip(),
            "disaster_number":         str(r.get("disaster_number", "")).strip(),
            "grant_amount":            grant_amt,
            "amount_drawn":            amount_drawn,
            "amount_remaining":        amount_remaining,
            "disbursement_rate":       disbursement_rate,
            "activity_count":          activity_counts.get(gn, 0),
            "completed_activity_count": completed_counts.get(gn, 0),
            "source_system":           "hud_drgr",
        })

    df_out = pd.DataFrame(rows, columns=PROJECT_COLUMNS) if rows else pd.DataFrame(columns=PROJECT_COLUMNS)
    logger.info(f"  Projects: {len(df_out):,} grants/appropriations")
    return df_out


def _build_responsible_orgs(df_activities, logger):
    """Aggregate unique responsible orgs from activities."""
    if df_activities.empty or "responsible_org" not in df_activities.columns:
        logger.warning("  No activity data for responsible org resolution")
        return pd.DataFrame(columns=ORG_COLUMNS)

    org_col = "responsible_org"
    norm_col = "responsible_org_normalized" if "responsible_org_normalized" in df_activities.columns else None

    rows = []
    for org, grp in df_activities.groupby(org_col):
        if not str(org).strip():
            continue
        norm = _normalize_name(str(org))
        grant_nums = grp.get("grant_number", pd.Series(dtype=str)).dropna().unique().tolist()
        total_budget = _to_num(grp.get("total_budget", pd.Series(dtype=float))).sum()
        total_drawn = _to_num(grp.get("amount_drawn", pd.Series(dtype=float))).sum()
        rows.append({
            "responsible_org":           str(org).strip(),
            "responsible_org_normalized": norm,
            "grant_number_list":         ",".join(str(g) for g in grant_nums if g),
            "activity_count":            len(grp),
            "total_budget_managed":      total_budget,
            "total_drawn":               total_drawn,
        })

    df_out = pd.DataFrame(rows, columns=ORG_COLUMNS) if rows else pd.DataFrame(columns=ORG_COLUMNS)
    df_out = df_out.sort_values("total_budget_managed", ascending=False).reset_index(drop=True)
    logger.info(f"  Responsible orgs: {len(df_out):,} unique orgs")
    return df_out


def run(root=None, force=False):
    root = Path(root or PROJECT_ROOT)
    norm_dir = root / "data" / "normalized"
    norm_dir.mkdir(parents=True, exist_ok=True)

    project_path = norm_dir / "hud_drgr_projects.parquet"
    org_path     = norm_dir / "hud_drgr_responsible_orgs_resolved.parquet"
    logger = setup_logging("normalize_hud_drgr")

    if not force and project_path.exists() and org_path.exists():
        p_rows = len(pq_read(project_path))
        logger.info(f"  hud_drgr_projects.parquet exists ({p_rows:,} rows) — skipping.")
        return {"project_rows": p_rows, "org_rows": 0, "status": "CACHED"}

    logger.info("Loading HUD DRGR inputs...")
    df_grants        = _load(norm_dir / "hud_drgr_grants.parquet", logger)
    df_activities    = _load(norm_dir / "hud_drgr_activities.parquet", logger)
    df_drawdowns     = _load(norm_dir / "hud_drgr_drawdowns.parquet", logger)
    df_appropriations = _load(norm_dir / "hud_drgr_appropriations.parquet", logger)

    # Normalize responsible org names in activities
    if not df_activities.empty and "responsible_org" in df_activities.columns:
        df_activities["responsible_org_normalized"] = df_activities["responsible_org"].apply(_normalize_name)

    # Validate: flag activities where drawn > budget
    if not df_activities.empty:
        budget = pd.to_numeric(df_activities.get("total_budget", pd.Series(dtype=float)), errors="coerce").fillna(0)
        drawn  = pd.to_numeric(df_activities.get("amount_drawn", pd.Series(dtype=float)), errors="coerce").fillna(0)
        overdrawn = (drawn > budget) & (budget > 0)
        if overdrawn.sum() > 0:
            logger.warning(f"  {overdrawn.sum()} activities have amount_drawn > total_budget")

    df_projects = _build_projects(df_grants, df_appropriations, df_activities, logger)
    pq_write(df_projects, project_path)
    logger.info(f"  Projects → {project_path.name}")

    df_orgs = _build_responsible_orgs(df_activities, logger)
    pq_write(df_orgs, org_path)
    logger.info(f"  Responsible orgs → {org_path.name}")

    return {"project_rows": len(df_projects), "org_rows": len(df_orgs), "status": "OK"}


def main():
    parser = argparse.ArgumentParser(description="Normalize HUD DRGR data")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    result = run(force=args.force)
    print(f"\nHUD DRGR normalize: {result['project_rows']:,} projects, {result['org_rows']:,} orgs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
