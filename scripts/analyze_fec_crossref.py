"""
Cross-reference FEC campaign contributions against the unified awards master.

Identifies Puerto Rico entities that appear as both:
  - Federal award recipients (contracts, grants, loans) in pr_all_awards_master.csv
  - Campaign contributors in pr_fec_contributions.csv

Matching is done on normalized entity names (uppercase, stripped punctuation).

Output:
  data/staging/processed/pr_fec_crossref.csv
    One row per matched entity showing:
      - Normalized name used for matching
      - Total federal awards obligated
      - Total FEC contributions
      - Number of awards, datasets involved
      - Number of FEC contributions, candidates/committees funded
      - Most recent contribution date

Usage:
  python3 scripts/analyze_fec_crossref.py
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from scripts.config import PROCESSED_DIR, PROJECT_ROOT, setup_logging


# ---------------------------------------------------------------------------
# Name normalization
# ---------------------------------------------------------------------------

_STRIP_RE = re.compile(r"[^\w\s]")
_SPACE_RE = re.compile(r"\s+")
_SUFFIXES = {
    "INC", "LLC", "LLP", "CORP", "CO", "LTD", "LP", "PC",
    "PLLC", "DBA", "THE", "AND", "OF",
}


def _normalize(name: str) -> str:
    """Uppercase, strip punctuation, collapse spaces, remove common suffixes."""
    if not name or pd.isna(name):
        return ""
    n = str(name).upper()
    n = _STRIP_RE.sub(" ", n)
    n = _SPACE_RE.sub(" ", n).strip()
    # Remove trailing legal suffixes (single pass)
    tokens = n.split()
    while tokens and tokens[-1] in _SUFFIXES:
        tokens.pop()
    return " ".join(tokens)


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

def build_crossref(root: Path = None) -> dict:
    if root is None:
        root = PROJECT_ROOT

    root = Path(root)
    processed_dir = root / "data" / "staging" / "processed"
    logger = setup_logging("analyze_fec_crossref")

    awards_path = processed_dir / "pr_all_awards_master.csv"
    fec_path    = processed_dir / "pr_fec_contributions.csv"
    out_path    = processed_dir / "pr_fec_crossref.csv"

    if not awards_path.exists():
        logger.error(f"  Awards master not found: {awards_path}")
        logger.error("  Run build_unified_master.py first.")
        return {"rows": 0, "status": "MISSING_AWARDS"}

    if not fec_path.exists():
        logger.error(f"  FEC contributions not found: {fec_path}")
        logger.error("  Run download_fec.py first.")
        return {"rows": 0, "status": "MISSING_FEC"}

    logger.info("Loading awards master...")
    awards = pd.read_csv(awards_path, dtype=str, low_memory=False)
    logger.info(f"  {len(awards):,} award rows")

    logger.info("Loading FEC contributions...")
    fec = pd.read_csv(fec_path, dtype=str, low_memory=False)
    logger.info(f"  {len(fec):,} FEC contribution rows")

    # ------------------------------------------------------------------
    # Build normalized award-recipient index
    # ------------------------------------------------------------------
    awards["_norm_name"] = awards["recipient_name"].apply(_normalize)
    awards["_amount"]    = pd.to_numeric(awards["obligated_amount"], errors="coerce").fillna(0)

    award_index = (
        awards[awards["_norm_name"] != ""]
        .groupby("_norm_name")
        .agg(
            award_recipient_name  = ("recipient_name",  "first"),
            total_awards_obligated= ("_amount",         "sum"),
            award_count           = ("award_id",        "nunique"),
            datasets              = ("source_dataset",  lambda x: "|".join(sorted(x.dropna().unique()))),
        )
        .reset_index()
    )
    logger.info(f"  {len(award_index):,} unique normalized award recipients")

    # ------------------------------------------------------------------
    # Build normalized FEC-contributor index
    # ------------------------------------------------------------------
    fec["_norm_name"] = fec["contributor_name"].apply(_normalize)
    fec["_amount"]    = pd.to_numeric(fec["contribution_receipt_amount"], errors="coerce").fillna(0)

    fec_index = (
        fec[fec["_norm_name"] != ""]
        .groupby("_norm_name")
        .agg(
            fec_contributor_name   = ("contributor_name",            "first"),
            total_contributions    = ("_amount",                     "sum"),
            contribution_count     = ("contribution_receipt_amount", "count"),
            committees_funded      = ("committee_name",   lambda x: "|".join(sorted(x.dropna().unique())[:10])),
            candidates_funded      = ("candidate_name",   lambda x: "|".join(sorted(x[x != ""].dropna().unique())[:10])),
            latest_contribution    = ("contribution_receipt_date",   "max"),
            earliest_contribution  = ("contribution_receipt_date",   "min"),
        )
        .reset_index()
    )
    logger.info(f"  {len(fec_index):,} unique normalized FEC contributors")

    # ------------------------------------------------------------------
    # Inner join on normalized name
    # ------------------------------------------------------------------
    merged = award_index.merge(fec_index, on="_norm_name", how="inner")
    logger.info(f"  {len(merged):,} entities appear in both awards and FEC contributions")

    if merged.empty:
        logger.warning("  No cross-reference matches found.")
        merged = pd.DataFrame(columns=[
            "normalized_name", "award_recipient_name", "fec_contributor_name",
            "total_awards_obligated", "total_contributions", "award_count",
            "contribution_count", "datasets", "committees_funded",
            "candidates_funded", "latest_contribution", "earliest_contribution",
        ])
    else:
        merged = merged.rename(columns={"_norm_name": "normalized_name"})
        merged = merged.sort_values("total_awards_obligated", ascending=False)

    merged.to_csv(out_path, index=False, encoding="utf-8")
    logger.info(f"  Written: {out_path.name} ({len(merged):,} matched entities)")

    # Summary stats
    if not merged.empty:
        total_awards_val  = merged["total_awards_obligated"].sum()
        total_contrib_val = merged["total_contributions"].sum()
        logger.info("=" * 60)
        logger.info("FEC CROSS-REFERENCE SUMMARY")
        logger.info("=" * 60)
        logger.info(f"  Matched entities:          {len(merged):,}")
        logger.info(f"  Total awards to matched:   ${total_awards_val:,.2f}")
        logger.info(f"  Total contributions from:  ${total_contrib_val:,.2f}")
        logger.info(f"\n  Top 10 by awards received:")
        for _, row in merged.head(10).iterrows():
            logger.info(
                f"    {row['award_recipient_name'][:50]:<50} "
                f"${float(row['total_awards_obligated']):>15,.0f} awards  "
                f"${float(row['total_contributions']):>10,.0f} contributions"
            )

    return {
        "rows":   len(merged),
        "status": "OK" if not merged.empty else "EMPTY",
        "path":   str(out_path),
    }


def main() -> int:
    result = build_crossref()
    print(f"\nCross-reference complete: {result['rows']:,} matched entities → {result.get('path', '')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
