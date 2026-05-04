"""
Budget/drawdown/obligation reconciliation for HUD DRGR.

Inputs:
  data/normalized/hud_drgr_projects.parquet
  data/normalized/hud_drgr_activities.parquet
  data/normalized/hud_drgr_drawdowns.parquet

Output:
  data/validation/hud_drgr_amount_reconciliation.csv

Usage:
  python3 scripts/validate_hud_drgr_amounts.py
  python3 scripts/validate_hud_drgr_amounts.py --force
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from scripts.parquet_utils import pq_read, pq_write
from scripts.config import PROJECT_ROOT, setup_logging

VALIDATION_DIR = PROJECT_ROOT / "data" / "validation"

RECONCILIATION_COLUMNS = [
    "grant_number", "level",
    "entity_id",
    "budget_reported", "budget_computed",
    "variance_amount", "variance_pct",
    "flag",
    "review_note",
]

WARN_THRESHOLD_PCT = 1.0
FAIL_THRESHOLD_PCT = 10.0
WARN_THRESHOLD_ABS = 10_000


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


def _to_num(val):
    return pd.to_numeric(val, errors="coerce") or 0.0


def _flag(variance_pct, variance_abs):
    if abs(variance_pct) >= FAIL_THRESHOLD_PCT:
        return "FAIL >10%"
    if abs(variance_pct) >= WARN_THRESHOLD_PCT or abs(variance_abs) >= WARN_THRESHOLD_ABS:
        return "WARN >1%"
    return "OK"


def run(root=None, force=False):
    root = Path(root or PROJECT_ROOT)
    VALIDATION_DIR.mkdir(parents=True, exist_ok=True)
    out_path = root / "data" / "validation" / "hud_drgr_amount_reconciliation.csv"
    logger = setup_logging("validate_hud_drgr_amounts")

    if out_path.exists() and not force:
        rows = len(pd.read_csv(out_path, dtype=str, nrows=5000))
        logger.info(f"  hud_drgr_amount_reconciliation.csv exists ({rows:,} rows) — skipping.")
        return {"checked": rows, "flagged": 0, "flag_pct": 0.0, "status": "CACHED"}

    norm_dir = root / "data" / "normalized"
    df_projects   = _load_parquet(norm_dir / "hud_drgr_projects.parquet", logger)
    df_activities = _load_parquet(norm_dir / "hud_drgr_activities.parquet", logger)
    df_drawdowns  = _load_parquet(norm_dir / "hud_drgr_drawdowns.parquet", logger)

    rows = []

    # 1. Grant-level: sum activity budgets vs grant_amount
    if not df_projects.empty and not df_activities.empty:
        if "grant_number" in df_activities.columns and "grant_number" in df_projects.columns:
            act_budgets = (
                df_activities.groupby("grant_number")
                .apply(lambda g: pd.to_numeric(g.get("total_budget", pd.Series(dtype=float)), errors="coerce").fillna(0).sum())
                .rename("computed_budget")
                .reset_index()
            )
            for _, proj in df_projects.iterrows():
                gn = str(proj.get("grant_number", "")).strip()
                reported = float(pd.to_numeric(proj.get("grant_amount", 0), errors="coerce") or 0)
                match = act_budgets[act_budgets["grant_number"] == gn]
                computed = float(match["computed_budget"].iloc[0]) if not match.empty else 0.0
                variance_abs = computed - reported
                variance_pct = round(variance_abs / reported * 100, 2) if reported > 0 else 0.0
                flag = _flag(variance_pct, variance_abs)
                note = ""
                if flag != "OK":
                    note = f"Activity budgets (${computed:,.0f}) vs grant amount (${reported:,.0f})"
                rows.append({
                    "grant_number":    gn,
                    "level":           "grant",
                    "entity_id":       gn,
                    "budget_reported": reported,
                    "budget_computed": computed,
                    "variance_amount": variance_abs,
                    "variance_pct":    variance_pct,
                    "flag":            flag,
                    "review_note":     note,
                })

    # 2. Activity-level: sum drawdowns vs amount_drawn
    if not df_activities.empty and not df_drawdowns.empty:
        if "activity_id" in df_activities.columns and "activity_id" in df_drawdowns.columns:
            dd_sums = (
                df_drawdowns.groupby("activity_id")
                .apply(lambda g: pd.to_numeric(g.get("drawdown_amount", pd.Series(dtype=float)), errors="coerce").fillna(0).sum())
                .rename("sum_drawdowns")
                .reset_index()
            )
            for _, act in df_activities.iterrows():
                aid = str(act.get("activity_id", "")).strip()
                if not aid:
                    continue
                gn = str(act.get("grant_number", "")).strip()
                reported = float(pd.to_numeric(act.get("amount_drawn", 0), errors="coerce") or 0)
                match = dd_sums[dd_sums["activity_id"] == aid]
                computed = float(match["sum_drawdowns"].iloc[0]) if not match.empty else 0.0
                if reported == 0 and computed == 0:
                    continue
                variance_abs = computed - reported
                variance_pct = round(variance_abs / reported * 100, 2) if reported > 0 else 0.0
                flag = _flag(variance_pct, variance_abs)
                if flag == "OK":
                    continue
                note = f"Drawdown sum (${computed:,.0f}) vs activity amount_drawn (${reported:,.0f})"
                rows.append({
                    "grant_number":    gn,
                    "level":           "activity",
                    "entity_id":       aid,
                    "budget_reported": reported,
                    "budget_computed": computed,
                    "variance_amount": variance_abs,
                    "variance_pct":    variance_pct,
                    "flag":            flag,
                    "review_note":     note,
                })

    # 3. Disbursement rate outliers in projects
    if not df_projects.empty and "disbursement_rate" in df_projects.columns:
        for _, proj in df_projects.iterrows():
            rate = pd.to_numeric(proj.get("disbursement_rate", 0), errors="coerce") or 0
            if rate > 1.0 or (rate < 0.01 and float(pd.to_numeric(proj.get("grant_amount", 0), errors="coerce") or 0) > 1_000_000):
                gn = str(proj.get("grant_number", "")).strip()
                note = f"Disbursement rate {rate:.1%} {'(over 100%)' if rate > 1 else '(below 1% on large grant)'}"
                rows.append({
                    "grant_number":    gn,
                    "level":           "disbursement_rate",
                    "entity_id":       gn,
                    "budget_reported": float(pd.to_numeric(proj.get("grant_amount", 0), errors="coerce") or 0),
                    "budget_computed": float(pd.to_numeric(proj.get("amount_drawn", 0), errors="coerce") or 0),
                    "variance_amount": None,
                    "variance_pct":    round(rate * 100, 2),
                    "flag":            "FAIL >10%" if rate > 1.0 else "WARN >1%",
                    "review_note":     note,
                })

    df_out = pd.DataFrame(rows, columns=RECONCILIATION_COLUMNS) if rows else pd.DataFrame(columns=RECONCILIATION_COLUMNS)
    df_out.to_csv(out_path, index=False, encoding="utf-8")

    flagged = (df_out["flag"] != "OK").sum() if not df_out.empty else 0
    flag_pct = round(flagged / len(df_out) * 100, 1) if len(df_out) > 0 else 0.0

    logger.info(f"  Amount reconciliation: {len(df_out):,} checks, {flagged} flagged ({flag_pct:.1f}%)")
    logger.info(f"  → {out_path.name}")

    return {"checked": len(df_out), "flagged": flagged, "flag_pct": flag_pct, "status": "OK"}


def main():
    parser = argparse.ArgumentParser(description="Validate HUD DRGR budget/drawdown amounts")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    result = run(force=args.force)
    print(f"\nHUD DRGR amounts: {result['checked']:,} checks, {result['flagged']} flagged ({result['flag_pct']:.1f}%)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
