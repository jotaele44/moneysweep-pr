"""
Cross-reference LDA lobbying clients against the unified awards master.

Identifies Puerto Rico entities that appear as both:
  - Federal award recipients in pr_all_awards_master.csv
  - LDA lobbying clients (hired federal lobbyists) in pr_lda_filings.csv

The influence loop: entity receives federal funds → hires DC lobbyists
→ lobbies for more federal spending / favorable policy → receives more funds.

Matching is done on normalized entity names (uppercase, stripped punctuation).

Output:
  data/staging/processed/pr_lobbying_crossref.csv
    One row per matched entity showing:
      - Normalized name used for matching
      - Total federal awards obligated
      - Total lobbying spend (client expenses) and income to registrants
      - Filing count, years active, issue areas lobbied
      - Lobbyists hired, agencies targeted

Usage:
  python3 scripts/analyze_lobbying_crossref.py
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from scripts.config import PROCESSED_DIR, PROJECT_ROOT, setup_logging


# ---------------------------------------------------------------------------
# Name normalization (same logic as analyze_fec_crossref.py)
# ---------------------------------------------------------------------------

_STRIP_RE = re.compile(r"[^\w\s]")
_SPACE_RE = re.compile(r"\s+")
_SUFFIXES = {
    "INC", "LLC", "LLP", "CORP", "CO", "LTD", "LP", "PC",
    "PLLC", "DBA", "THE", "AND", "OF", "SA", "SL", "SRL",
}


def _normalize(name: str) -> str:
    if not name or pd.isna(name):
        return ""
    n = str(name).upper()
    n = _STRIP_RE.sub(" ", n)
    n = _SPACE_RE.sub(" ", n).strip()
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

    root          = Path(root)
    processed_dir = root / "data" / "staging" / "processed"
    logger        = setup_logging("analyze_lobbying_crossref")

    awards_path  = processed_dir / "pr_all_awards_master.csv"
    lda_path     = processed_dir / "pr_lda_filings.csv"
    out_path     = processed_dir / "pr_lobbying_crossref.csv"

    if not awards_path.exists():
        logger.error(f"  Awards master not found: {awards_path}")
        logger.error("  Run build_unified_master.py first.")
        return {"rows": 0, "status": "MISSING_AWARDS"}

    if not lda_path.exists():
        logger.error(f"  LDA filings not found: {lda_path}")
        logger.error("  Run download_lda.py first.")
        return {"rows": 0, "status": "MISSING_LDA"}

    logger.info("Loading awards master...")
    awards = pd.read_csv(awards_path, dtype=str, low_memory=False)
    logger.info(f"  {len(awards):,} award rows")

    logger.info("Loading LDA filings...")
    lda = pd.read_csv(lda_path, dtype=str, low_memory=False)
    logger.info(f"  {len(lda):,} LDA filing rows")

    # ------------------------------------------------------------------
    # Build normalized award-recipient index
    # ------------------------------------------------------------------
    awards["_norm"] = awards["recipient_name"].apply(_normalize)
    awards["_amt"]  = pd.to_numeric(awards["obligated_amount"], errors="coerce").fillna(0)

    award_index = (
        awards[awards["_norm"] != ""]
        .groupby("_norm")
        .agg(
            award_recipient_name   = ("recipient_name",  "first"),
            total_awards_obligated = ("_amt",            "sum"),
            award_count            = ("award_id",        "nunique"),
            award_datasets         = ("source_dataset",  lambda x: "|".join(sorted(x.dropna().unique()))),
            award_years            = ("fiscal_year",     lambda x: _year_range(x)),
        )
        .reset_index()
    )
    logger.info(f"  {len(award_index):,} unique normalized award recipients")

    # ------------------------------------------------------------------
    # Build normalized LDA-client index
    # ------------------------------------------------------------------
    # Keep only client-side rows (where the PR entity is the client paying lobbyists)
    lda_clients = lda[lda["client_state"] == "PR"].copy()
    if lda_clients.empty:
        # Fall back to all rows if state field is blank
        lda_clients = lda.copy()

    lda_clients["_norm"]    = lda_clients["client_name"].apply(_normalize)
    lda_clients["_income"]  = pd.to_numeric(lda_clients["income"],   errors="coerce").fillna(0)
    lda_clients["_expense"] = pd.to_numeric(lda_clients["expenses"], errors="coerce").fillna(0)

    lda_index = (
        lda_clients[lda_clients["_norm"] != ""]
        .groupby("_norm")
        .agg(
            lda_client_name         = ("client_name",          "first"),
            lda_client_description  = ("client_description",   "first"),
            filing_count            = ("filing_uuid",          "nunique"),
            total_registrant_income = ("_income",              "sum"),
            total_client_expenses   = ("_expense",             "sum"),
            years_active            = ("filing_year",          lambda x: _year_range(x)),
            issue_codes             = ("general_issue_codes",  lambda x: _merge_pipe(x, 15)),
            lobbyists_hired         = ("lobbyist_names",       lambda x: _merge_pipe(x, 20)),
            registrants_used        = ("registrant_name",      lambda x: "|".join(sorted(x.dropna().unique())[:10])),
        )
        .reset_index()
    )
    logger.info(f"  {len(lda_index):,} unique normalized LDA clients")

    # ------------------------------------------------------------------
    # Inner join
    # ------------------------------------------------------------------
    merged = award_index.merge(lda_index, on="_norm", how="inner")
    logger.info(f"  {len(merged):,} entities appear in both awards and LDA filings")

    if merged.empty:
        logger.warning("  No lobbying cross-reference matches found.")
        merged = pd.DataFrame(columns=[
            "normalized_name", "award_recipient_name", "lda_client_name",
            "lda_client_description", "total_awards_obligated", "award_count",
            "award_datasets", "award_years", "filing_count",
            "total_registrant_income", "total_client_expenses",
            "years_active", "issue_codes", "lobbyists_hired", "registrants_used",
        ])
    else:
        merged = merged.rename(columns={"_norm": "normalized_name"})
        merged = merged.sort_values("total_awards_obligated", ascending=False)

    merged.to_csv(out_path, index=False, encoding="utf-8")
    logger.info(f"  Written: {out_path.name} ({len(merged):,} matched entities)")

    if not merged.empty:
        total_awards  = merged["total_awards_obligated"].sum()
        total_spend   = merged["total_client_expenses"].sum()
        total_income  = merged["total_registrant_income"].sum()
        logger.info("=" * 60)
        logger.info("LOBBYING CROSS-REFERENCE SUMMARY")
        logger.info("=" * 60)
        logger.info(f"  Matched entities:          {len(merged):,}")
        logger.info(f"  Total awards to matched:   ${float(total_awards):,.0f}")
        lobby_val = float(total_spend) if float(total_spend) > 0 else float(total_income)
        logger.info(f"  Total lobbying spend:      ${lobby_val:,.0f}")
        logger.info(f"\n  Top 10 by awards received:")
        for _, row in merged.head(10).iterrows():
            name  = str(row["award_recipient_name"])[:48]
            award = float(row["total_awards_obligated"])
            spend = max(float(row["total_client_expenses"]), float(row["total_registrant_income"]))
            logger.info(f"    {name:<48}  ${award:>14,.0f} awards  ${spend:>10,.0f} lobbying")

    return {
        "rows":   len(merged),
        "status": "OK" if not merged.empty else "EMPTY",
        "path":   str(out_path),
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _year_range(series: pd.Series) -> str:
    vals = pd.to_numeric(series, errors="coerce").dropna()
    if vals.empty:
        return ""
    lo, hi = int(vals.min()), int(vals.max())
    return str(lo) if lo == hi else f"{lo}-{hi}"


def _merge_pipe(series: pd.Series, limit: int) -> str:
    seen, out = set(), []
    for cell in series.dropna():
        for part in str(cell).split("|"):
            part = part.strip()
            if part and part not in seen:
                seen.add(part)
                out.append(part)
                if len(out) >= limit:
                    return "|".join(out)
    return "|".join(out)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    result = build_crossref()
    print(f"\nLobbying cross-reference complete: {result['rows']:,} matched entities → {result.get('path', '')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
