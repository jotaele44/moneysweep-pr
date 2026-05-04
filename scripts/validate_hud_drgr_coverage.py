"""
Coverage and entity-resolution report for HUD DRGR.

Inputs:
  data/normalized/hud_drgr_activities.parquet
  data/normalized/hud_drgr_responsible_orgs_resolved.parquet
  data/linked/hud_drgr_financial_linkage.csv

Outputs:
  data/validation/hud_drgr_gap_report.csv
  data/review/hud_drgr_unlinked_activities.csv

Usage:
  python3 scripts/validate_hud_drgr_coverage.py
  python3 scripts/validate_hud_drgr_coverage.py --force
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from scripts.parquet_utils import pq_read, pq_write
from scripts.config import PROJECT_ROOT, setup_logging

VALIDATION_DIR = PROJECT_ROOT / "data" / "validation"
REVIEW_DIR     = PROJECT_ROOT / "data" / "review"

RESOLUTION_THRESHOLD = 0.90

GAP_COLUMNS = [
    "activity_id", "grant_number", "activity_name",
    "responsible_org", "total_budget", "gap_reason",
]


def _load_parquet(path, logger):
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


def _load_csv(path, logger):
    if not path.exists():
        return pd.DataFrame()
    try:
        df = pd.read_csv(path, dtype=str, low_memory=False)
        logger.info(f"  Loaded {len(df):,} rows from {path.name}")
        return df
    except Exception as e:
        logger.warning(f"  Failed to read {path.name}: {e}")
        return pd.DataFrame()


def run(root=None, force=False):
    root = Path(root or PROJECT_ROOT)
    VALIDATION_DIR.mkdir(parents=True, exist_ok=True)
    REVIEW_DIR.mkdir(parents=True, exist_ok=True)

    gap_path      = root / "data" / "validation" / "hud_drgr_gap_report.csv"
    unlinked_path = root / "data" / "review" / "hud_drgr_unlinked_activities.csv"
    logger = setup_logging("validate_hud_drgr_coverage")

    if gap_path.exists() and not force:
        logger.info("  HUD DRGR coverage outputs exist — skipping. Use --force to re-run.")
        return {"total_activities": 0, "resolved_pct": 0.0, "coverage_pass": False,
                "unlinked_count": 0, "status": "CACHED"}

    norm_dir = root / "data" / "normalized"
    linked_dir = root / "data" / "linked"

    df_activities = _load_parquet(norm_dir / "hud_drgr_activities.parquet", logger)
    df_orgs       = _load_parquet(norm_dir / "hud_drgr_responsible_orgs_resolved.parquet", logger)
    df_linkage    = _load_csv(linked_dir / "hud_drgr_financial_linkage.csv", logger)

    total_activities = len(df_activities) if not df_activities.empty else 0

    # Compute org resolution rate
    total_orgs = len(df_orgs) if not df_orgs.empty else 0
    if not df_linkage.empty and "link_confidence" in df_linkage.columns:
        resolved = (df_linkage["link_confidence"] != "none").sum()
        total_link_orgs = len(df_linkage)
    else:
        resolved = 0
        total_link_orgs = total_orgs

    resolved_pct = round(resolved / total_link_orgs * 100, 1) if total_link_orgs > 0 else 0.0
    coverage_pass = resolved_pct >= (RESOLUTION_THRESHOLD * 100)

    logger.info(f"  Org resolution: {resolved}/{total_link_orgs} ({resolved_pct:.1f}%) — "
                f"{'PASS' if coverage_pass else 'BELOW 90% THRESHOLD'}")

    # Gap report: activities with no responsible org or no entity linkage
    gap_rows = []
    if not df_activities.empty:
        linked_orgs = set()
        if not df_linkage.empty and "responsible_org_normalized" in df_linkage.columns:
            linked_orgs = set(
                df_linkage[df_linkage["link_confidence"] != "none"]["responsible_org_normalized"].dropna()
            )

        for _, act in df_activities.iterrows():
            resp_org = str(act.get("responsible_org", "")).strip()
            resp_norm = str(act.get("responsible_org_normalized", "")).strip()
            gap_reason = None

            if not resp_org:
                gap_reason = "no_responsible_org"
            elif resp_norm and resp_norm not in linked_orgs:
                gap_reason = "org_not_linked_to_contract"

            if gap_reason:
                gap_rows.append({
                    "activity_id":    act.get("activity_id", ""),
                    "grant_number":   act.get("grant_number", ""),
                    "activity_name":  act.get("activity_name", ""),
                    "responsible_org": resp_org,
                    "total_budget":   act.get("total_budget", ""),
                    "gap_reason":     gap_reason,
                })

    df_gap = pd.DataFrame(gap_rows, columns=GAP_COLUMNS) if gap_rows else pd.DataFrame(columns=GAP_COLUMNS)
    df_gap.to_csv(gap_path, index=False, encoding="utf-8")
    logger.info(f"  Gap report: {len(df_gap):,} rows → {gap_path.name}")

    # Unlinked activities: no entity match and high value
    HIGH_VALUE = 500_000
    unlinked_rows = []
    if not df_activities.empty:
        for _, act in df_activities.iterrows():
            budget = pd.to_numeric(act.get("total_budget", 0), errors="coerce") or 0
            resp_org = str(act.get("responsible_org", "")).strip()
            resp_norm = str(act.get("responsible_org_normalized", "")).strip()
            if not resp_norm or (resp_norm not in linked_orgs and budget >= HIGH_VALUE):
                unlinked_rows.append({
                    "activity_id":    act.get("activity_id", ""),
                    "grant_number":   act.get("grant_number", ""),
                    "activity_name":  act.get("activity_name", ""),
                    "responsible_org": resp_org,
                    "total_budget":   budget,
                    "gap_reason":     "unlinked" if resp_org else "no_org",
                })

    df_unlinked = pd.DataFrame(unlinked_rows) if unlinked_rows else pd.DataFrame(columns=GAP_COLUMNS)
    df_unlinked.to_csv(unlinked_path, index=False, encoding="utf-8")
    logger.info(f"  Unlinked activities: {len(df_unlinked):,} → {unlinked_path.name}")

    logger.info("=" * 60)
    logger.info("HUD DRGR COVERAGE SUMMARY")
    logger.info("=" * 60)
    logger.info(f"  Total activities:    {total_activities:,}")
    logger.info(f"  Org resolution:      {resolved_pct:.1f}% — {'PASS' if coverage_pass else 'BELOW THRESHOLD'}")
    logger.info(f"  Gap rows:            {len(df_gap):,}")
    logger.info(f"  Unlinked activities: {len(df_unlinked):,}")

    return {
        "total_activities": total_activities,
        "resolved_pct": resolved_pct,
        "coverage_pass": coverage_pass,
        "unlinked_count": len(df_unlinked),
        "status": "OK",
    }


def main():
    parser = argparse.ArgumentParser(description="Validate HUD DRGR coverage and entity resolution")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    result = run(force=args.force)
    print(f"\nHUD DRGR coverage: {result['resolved_pct']:.1f}% resolved, "
          f"{result['unlinked_count']} unlinked, {'PASS' if result['coverage_pass'] else 'FAIL'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
