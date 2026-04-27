"""
Score contractors on project delivery performance by synthesizing:
  - FEMA PA project completion rates
  - COR3 disbursement rates (approved vs. actually paid)
  - USACE permit status (does the contractor have required permits?)
  - EQB environmental compliance (open violations?)

Output: 0–100 delivery score + risk tier (low/medium/high) per entity.

Inputs:
  data/staging/processed/entity_master.csv
  data/staging/processed/pr_fema_pa_master.csv
  data/staging/processed/pr_cor3_projects.csv
  data/staging/processed/pr_usace_permits.csv
  data/staging/processed/pr_eqb_permits.csv

Output:
  data/staging/processed/pr_delivery_scorecard.csv

Usage:
  python3 scripts/analyze_project_delivery.py
  python3 scripts/analyze_project_delivery.py --force
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from scripts.config import PROCESSED_DIR, PROJECT_ROOT, setup_logging
from scripts.sam_enrichment import name_similarity

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Scoring weights (sum to 1.0)
WEIGHT_FEMA_COMPLETION    = 0.35
WEIGHT_COR3_DISBURSEMENT  = 0.30
WEIGHT_USACE_PERMIT       = 0.20
WEIGHT_EQB_COMPLIANCE     = 0.15

RISK_HIGH   = 40   # score < 40 → high risk
RISK_MEDIUM = 70   # score < 70 → medium risk

MATCH_THRESHOLD = 0.75  # vendor name match threshold

OUTPUT_COLUMNS = [
    "entity_key", "canonical_name", "total_awards_obligated", "award_count",
    "fema_projects_count", "fema_completion_rate",
    "cor3_projects_count", "cor3_disbursement_rate",
    "usace_permit_ok", "eqb_violation_flag", "eqb_violations",
    "delivery_score", "risk_tier",
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load(path: Path, label: str, logger) -> pd.DataFrame:
    if not path.exists():
        logger.warning(f"  {label} not found — {path.name}")
        return pd.DataFrame()
    df = pd.read_csv(path, dtype=str, low_memory=False)
    logger.info(f"  {label}: {len(df):,} rows")
    return df


def _safe_float(s) -> float:
    try:
        return float(s)
    except (TypeError, ValueError):
        return 0.0


def _match_name(entity_norm: str, df: pd.DataFrame, name_col: str) -> pd.DataFrame:
    """Return rows from df where name_col fuzzy-matches entity_norm."""
    if df.empty or not entity_norm:
        return pd.DataFrame()
    scores = df[name_col].apply(lambda n: name_similarity(entity_norm, str(n)))
    return df[scores >= MATCH_THRESHOLD].copy()


# ---------------------------------------------------------------------------
# Sub-scorers
# ---------------------------------------------------------------------------

def _fema_score(entity_norm: str, fema_df: pd.DataFrame) -> tuple[int, float]:
    """Return (project_count, completion_rate 0–1)."""
    if fema_df.empty:
        return 0, 0.5  # neutral if no FEMA data

    name_col = next(
        (c for c in ["recipient_name_normalized", "vendor_name", "recipient_name"]
         if c in fema_df.columns), None,
    )
    if not name_col:
        return 0, 0.5

    matched = _match_name(entity_norm, fema_df, name_col)
    if matched.empty:
        return 0, 0.5

    n = len(matched)
    status_col = next((c for c in ["project_status", "status"] if c in matched.columns), None)
    if status_col:
        completed = matched[status_col].str.lower().str.contains(
            "complete|closed|obligated|approved", na=False
        ).sum()
        rate = completed / n if n > 0 else 0.5
    else:
        rate = 0.5

    return n, round(rate, 3)


def _cor3_score(entity_norm: str, cor3_df: pd.DataFrame) -> tuple[int, float]:
    """Return (project_count, avg_disbursement_rate 0–1)."""
    if cor3_df.empty:
        return 0, 0.5

    matched = _match_name(entity_norm, cor3_df, "applicant_normalized")
    if matched.empty:
        return 0, 0.5

    n = len(matched)
    rates = pd.to_numeric(matched.get("disbursement_rate", pd.Series()), errors="coerce")
    avg_rate = rates.mean() if not rates.empty else 0.5
    return n, round(float(avg_rate), 3)


def _usace_ok(entity_norm: str, usace_df: pd.DataFrame) -> int:
    """1 if entity has an active USACE permit, 0 if none found."""
    if usace_df.empty:
        return 1  # neutral — assume OK if no permit data

    matched = _match_name(entity_norm, usace_df, "applicant_normalized")
    if matched.empty:
        return 0  # no permit record found

    status_col = next((c for c in ["status", "permit_status"] if c in matched.columns), None)
    if status_col:
        active = matched[status_col].str.lower().str.contains(
            "active|issued|valid|open", na=False
        ).any()
        return 1 if active else 0
    return 1


def _eqb_violations(entity_norm: str, eqb_df: pd.DataFrame) -> tuple[int, int]:
    """Return (violation_flag, violation_count)."""
    if eqb_df.empty:
        return 0, 0

    matched = _match_name(entity_norm, eqb_df, "facility_normalized")
    if matched.empty:
        return 0, 0

    total_viols = pd.to_numeric(matched.get("violation_count", pd.Series()), errors="coerce").sum()
    total_viols = int(total_viols)
    flag = 1 if total_viols > 0 else 0
    return flag, total_viols


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------

def run(root: Path = None, force: bool = False) -> dict:
    root = Path(root or PROJECT_ROOT)
    proc = root / "data" / "staging" / "processed"
    out_path = proc / "pr_delivery_scorecard.csv"
    proc.mkdir(parents=True, exist_ok=True)

    logger = setup_logging("analyze_project_delivery", log_dir=root / "data" / "logs")

    if out_path.exists() and not force:
        rows = sum(1 for _ in open(out_path)) - 1
        logger.info(f"  Delivery scorecard: exists ({rows:,} rows) — skipping (use --force).")
        return {"status": "CACHED", "rows": rows}

    # Load all inputs
    entity_df = _load(proc / "entity_master.csv", "entity_master", logger)
    fema_df   = _load(proc / "pr_fema_pa_master.csv", "FEMA PA", logger)
    cor3_df   = _load(proc / "pr_cor3_projects.csv", "COR3", logger)
    usace_df  = _load(proc / "pr_usace_permits.csv", "USACE permits", logger)
    eqb_df    = _load(proc / "pr_eqb_permits.csv", "EQB permits", logger)

    if entity_df.empty:
        logger.warning("  entity_master.csv missing — run build_unified_master.py first")
        pd.DataFrame(columns=OUTPUT_COLUMNS).to_csv(out_path, index=False)
        return {"status": "SKIPPED", "reason": "no_entity_master", "rows": 0}

    # Ensure normalized name column
    norm_col = "recipient_name_normalized" if "recipient_name_normalized" in entity_df.columns \
               else "canonical_name" if "canonical_name" in entity_df.columns else None

    rows = []
    for _, ent in entity_df.iterrows():
        entity_key   = str(ent.get("entity_key") or ent.get("canonical_name") or "")
        canonical    = str(ent.get("canonical_name") or ent.get("recipient_name_normalized") or "")
        entity_norm  = canonical  # already normalized in entity_master

        total_obligated = _safe_float(ent.get("total_obligated") or ent.get("total_obligation") or 0)
        award_count     = int(_safe_float(ent.get("award_count") or 0))

        # Sub-scores
        fema_n, fema_rate   = _fema_score(entity_norm, fema_df)
        cor3_n, cor3_rate   = _cor3_score(entity_norm, cor3_df)
        usace_ok            = _usace_ok(entity_norm, usace_df)
        eqb_flag, eqb_viols = _eqb_violations(entity_norm, eqb_df)

        # Composite score (0–100)
        score = (
            WEIGHT_FEMA_COMPLETION   * fema_rate  * 100
            + WEIGHT_COR3_DISBURSEMENT * cor3_rate  * 100
            + WEIGHT_USACE_PERMIT      * usace_ok   * 100
            + WEIGHT_EQB_COMPLIANCE    * (1 - eqb_flag) * 100
        )
        score = round(score, 1)

        if score < RISK_HIGH:
            risk_tier = "high"
        elif score < RISK_MEDIUM:
            risk_tier = "medium"
        else:
            risk_tier = "low"

        rows.append({
            "entity_key":             entity_key,
            "canonical_name":         canonical,
            "total_awards_obligated": total_obligated,
            "award_count":            award_count,
            "fema_projects_count":    fema_n,
            "fema_completion_rate":   fema_rate,
            "cor3_projects_count":    cor3_n,
            "cor3_disbursement_rate": cor3_rate,
            "usace_permit_ok":        usace_ok,
            "eqb_violation_flag":     eqb_flag,
            "eqb_violations":         eqb_viols,
            "delivery_score":         score,
            "risk_tier":              risk_tier,
        })

    df_out = pd.DataFrame(rows, columns=OUTPUT_COLUMNS)
    df_out = df_out.sort_values("delivery_score", ascending=False)
    df_out.to_csv(out_path, index=False)

    n = len(df_out)
    high_risk = (df_out["risk_tier"] == "high").sum()
    logger.info(f"  Delivery scorecard: {n:,} entities scored, {high_risk:,} high-risk → {out_path.name}")

    return {"status": "OK", "rows": n, "high_risk_count": int(high_risk)}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Score contractor project delivery performance")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    result = run(force=args.force)
    return 0 if result.get("status") in ("OK", "CACHED", "SKIPPED") else 1


if __name__ == "__main__":
    sys.exit(main())
