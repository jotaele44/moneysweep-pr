"""
Analyze prime-to-subcontractor relationships from the subawards master.

Reads pr_subawards_master.csv (which includes prime_recipient_name and
prime_award_id fields) and builds a directed relationship network:
  prime contractor → subcontractor → dollar flow

Surfaces:
  - Entities that appear ONLY as subcontractors (never prime)
  - Prime contractors with the broadest subcontractor networks
  - Dollar flows concentrated between specific prime-sub pairs
  - Subcontractors receiving large flows not in the main awards spine

Outputs:
  data/staging/processed/pr_prime_sub_relationships.csv
    One row per (prime, sub) pair with aggregated flow, contract count,
    agency, and date range.

  data/staging/processed/pr_prime_sub_summary.json
    Top primes, top subs, concentration metrics.

Usage:
  python3 scripts/analyze_prime_sub.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from scripts.config import PROCESSED_DIR, PROJECT_ROOT, setup_logging


def _yr_range(series: pd.Series) -> str:
    vals = pd.to_numeric(series, errors="coerce").dropna()
    if vals.empty:
        return ""
    lo, hi = int(vals.min()), int(vals.max())
    return str(lo) if lo == hi else f"{lo}-{hi}"


# ---------------------------------------------------------------------------

def build_prime_sub(root: Path = None) -> dict:
    if root is None:
        root = PROJECT_ROOT

    root      = Path(root)
    proc_dir  = root / "data" / "staging" / "processed"
    logger    = setup_logging("analyze_prime_sub")

    sub_path    = proc_dir / "pr_subawards_master.csv"
    awards_path = proc_dir / "pr_all_awards_master.csv"
    out_path    = proc_dir / "pr_prime_sub_relationships.csv"
    summary_path = proc_dir / "pr_prime_sub_summary.json"

    if not sub_path.exists():
        logger.error("  pr_subawards_master.csv not found — run download_subawards.py first")
        return {"rows": 0, "status": "MISSING_SUBAWARDS"}

    logger.info("Loading subawards master...")
    subs = pd.read_csv(sub_path, dtype=str, low_memory=False)
    logger.info(f"  {len(subs):,} subaward rows")

    # Require both sides of the relationship
    required = ["prime_recipient_name", "recipient_name"]
    missing  = [c for c in required if c not in subs.columns]
    if missing:
        logger.error(f"  Missing required columns: {missing}")
        return {"rows": 0, "status": f"MISSING_COLUMNS:{missing}"}

    subs = subs[
        subs["prime_recipient_name"].notna() & (subs["prime_recipient_name"] != "") &
        subs["recipient_name"].notna()       & (subs["recipient_name"] != "")
    ].copy()
    logger.info(f"  {len(subs):,} rows with both prime and sub names")

    subs["_amount"] = pd.to_numeric(subs["obligated_amount"], errors="coerce").fillna(0)

    # ------------------------------------------------------------------
    # Build (prime, sub) edge table
    # ------------------------------------------------------------------
    edges = (
        subs.groupby(["prime_recipient_name", "recipient_name"])
        .agg(
            total_flow        = ("_amount",         "sum"),
            contract_count    = ("award_id",        "nunique"),
            awarding_agencies = ("awarding_agency", lambda x: "|".join(sorted(x.dropna().unique())[:3])),
            prime_award_ids   = ("prime_award_id",  lambda x: "|".join(sorted(x.dropna().unique())[:5])),
            fiscal_year_range = ("fiscal_year",     _yr_range),
        )
        .reset_index()
        .rename(columns={
            "prime_recipient_name": "prime_recipient",
            "recipient_name":       "sub_recipient",
        })
        .sort_values("total_flow", ascending=False)
        .reset_index(drop=True)
    )

    edges.to_csv(out_path, index=False, encoding="utf-8")
    logger.info(f"  Written: {out_path.name} ({len(edges):,} prime-sub pairs)")

    # ------------------------------------------------------------------
    # Identify sub-only entities (not in awards master as primes)
    # ------------------------------------------------------------------
    prime_names = set(subs["prime_recipient_name"].dropna().unique())
    sub_names   = set(subs["recipient_name"].dropna().unique())
    sub_only    = sub_names - prime_names

    if awards_path.exists():
        awards = pd.read_csv(awards_path, dtype=str, low_memory=False)
        prime_names_in_master = set(awards["recipient_name"].dropna().unique())
        sub_only -= prime_names_in_master
    else:
        prime_names_in_master = set()

    sub_only_flows = (
        subs[subs["recipient_name"].isin(sub_only)]
        .groupby("recipient_name")
        .agg(total_flow=("_amount", "sum"), contract_count=("award_id", "nunique"))
        .reset_index()
        .sort_values("total_flow", ascending=False)
    )
    logger.info(f"  {len(sub_only):,} entities appear only as subcontractors "
                f"({len(sub_only_flows[sub_only_flows['total_flow'] > 100_000]):,} with >$100K flow)")

    # ------------------------------------------------------------------
    # Summary statistics
    # ------------------------------------------------------------------
    top_primes = (
        edges.groupby("prime_recipient")
        .agg(total_flow=("total_flow", "sum"), sub_count=("sub_recipient", "nunique"))
        .reset_index()
        .sort_values("total_flow", ascending=False)
        .head(10)
        .to_dict("records")
    )
    top_subs = (
        edges.groupby("sub_recipient")
        .agg(total_flow=("total_flow", "sum"), prime_count=("prime_recipient", "nunique"))
        .reset_index()
        .sort_values("total_flow", ascending=False)
        .head(10)
        .to_dict("records")
    )
    top_pairs = edges.head(10).to_dict("records")

    total_sub_flow = float(edges["total_flow"].sum())
    summary = {
        "prime_count":        int(edges["prime_recipient"].nunique()),
        "sub_count":          int(edges["sub_recipient"].nunique()),
        "pair_count":         len(edges),
        "sub_only_count":     len(sub_only),
        "total_sub_flow":     total_sub_flow,
        "top_primes":         top_primes,
        "top_subs":           top_subs,
        "top_pairs":          top_pairs,
    }
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, default=str)
    logger.info(f"  Written: {summary_path.name}")

    logger.info("=" * 60)
    logger.info("PRIME-TO-SUB RELATIONSHIP SUMMARY")
    logger.info("=" * 60)
    logger.info(f"  Unique prime contractors:  {summary['prime_count']:,}")
    logger.info(f"  Unique subcontractors:     {summary['sub_count']:,}")
    logger.info(f"  Unique prime-sub pairs:    {summary['pair_count']:,}")
    logger.info(f"  Sub-only entities:         {summary['sub_only_count']:,}")
    logger.info(f"  Total sub-award flow:      ${total_sub_flow:,.0f}")

    logger.info("\n  Top primes by sub-award flow:")
    for row in top_primes[:5]:
        logger.info(f"    {str(row['prime_recipient'])[:50]:<50}  "
                    f"${float(row['total_flow']):>14,.0f}  "
                    f"({int(row['sub_count'])} subs)")

    logger.info("\n  Top prime-sub pairs by flow:")
    for row in top_pairs[:5]:
        logger.info(f"    {str(row['prime_recipient'])[:30]:<30} → "
                    f"{str(row['sub_recipient'])[:30]:<30}  "
                    f"${float(row['total_flow']):>14,.0f}")

    return {
        "rows":         len(edges),
        "prime_count":  summary["prime_count"],
        "sub_count":    summary["sub_count"],
        "sub_only":     len(sub_only),
        "total_flow":   total_sub_flow,
        "status":       "OK",
        "out_path":     str(out_path),
        "summary_path": str(summary_path),
    }


def main() -> int:
    result = build_prime_sub()
    print(f"\nPrime-sub analysis complete: {result['rows']:,} pairs, "
          f"{result['prime_count']:,} primes, {result['sub_count']:,} subs, "
          f"${result.get('total_flow', 0):,.0f} total flow.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
