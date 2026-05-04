"""
Cross-reference PR government RFPs with LDA federal lobbying filings to quantify
lobby influence on procurement timing and contractor selection.

Key question: Did the eventual RFP winner have active federal lobbying filings
in the 180 days before the RFP was posted? If so, the contractor may have
shaped the procurement specifications.

Inputs:
  data/staging/processed/pr_compras_rfps.csv     — RFPs from Compras PR
  data/staging/processed/pr_compras_awards.csv   — Contract awards from Compras PR
  data/staging/processed/pr_lda_filings.csv      — LDA lobbying filings (step 18)
  data/staging/processed/entity_lda_enriched.csv — Entity LDA enrichment (step 18b)

Output:
  data/staging/processed/pr_rfp_lobby_crossref.csv

Usage:
  python3 scripts/analyze_rfp_lobby.py
  python3 scripts/analyze_rfp_lobby.py --window-days 180
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from scripts.config import PROCESSED_DIR, PROJECT_ROOT, setup_logging
from scripts.build_unified_master import _normalize_name
from scripts.sam_enrichment import name_similarity

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

WINDOW_DAYS = 180   # lobbying activity window before RFP posting
MIN_SCORE   = 0.70  # min vendor name match score to link RFP award to LDA entity

OUTPUT_COLUMNS = [
    "rfp_id", "title", "agency", "posted_date", "due_date",
    "awarded_vendor", "awarded_vendor_normalized",
    "lda_flag", "lobby_lead_days", "lda_spend_prior_window",
    "lda_registrants_prior", "lda_issues_prior",
    "lda_filings_prior_count", "influence_score",
]

# ---------------------------------------------------------------------------
# Load helpers
# ---------------------------------------------------------------------------

def _load_csv(path: Path, label: str, logger) -> pd.DataFrame | None:
    if not path.exists():
        logger.warning(f"  {label} not found: {path.name} — run prerequisite steps first")
        return None
    df = pd.read_csv(path, dtype=str, low_memory=False)
    logger.info(f"  {label}: {len(df):,} rows")
    return df


# ---------------------------------------------------------------------------
# Core analysis
# ---------------------------------------------------------------------------

def _parse_dates(df: pd.DataFrame, col: str) -> pd.Series:
    return pd.to_datetime(df[col], errors="coerce", format="mixed")


def _match_vendor_to_lda(vendor_norm: str, lda_df: pd.DataFrame) -> pd.DataFrame:
    """Return LDA filings whose client name is a strong match for the vendor."""
    if not vendor_norm or lda_df.empty:
        return pd.DataFrame()
    client_norms = lda_df["client_name_normalized"] if "client_name_normalized" in lda_df.columns else pd.Series([], dtype=str)
    if client_norms.empty:
        return pd.DataFrame()
    scores = client_norms.apply(lambda cn: name_similarity(vendor_norm, cn))
    return lda_df[scores >= MIN_SCORE].copy()


def run(root: Path = None, window_days: int = WINDOW_DAYS) -> dict:
    root = Path(root or PROJECT_ROOT)
    proc = root / "data" / "staging" / "processed"
    out_path = proc / "pr_rfp_lobby_crossref.csv"
    proc.mkdir(parents=True, exist_ok=True)

    logger = setup_logging("analyze_rfp_lobby", log_dir=root / "data" / "logs")

    # Load inputs
    rfp_df   = _load_csv(proc / "pr_compras_rfps.csv",   "Compras RFPs",   logger)
    award_df = _load_csv(proc / "pr_compras_awards.csv", "Compras awards", logger)
    lda_df   = _load_csv(proc / "pr_lda_filings.csv",    "LDA filings",    logger)

    # If no RFPs, write empty and exit
    if rfp_df is None or rfp_df.empty:
        logger.warning("  No Compras RFP data — run download_compras.py first")
        pd.DataFrame(columns=OUTPUT_COLUMNS).to_csv(out_path, index=False)
        return {"status": "SKIPPED", "reason": "no_rfp_data", "rows": 0}

    if lda_df is None or lda_df.empty:
        logger.warning("  No LDA data — run download_lda.py first")
        pd.DataFrame(columns=OUTPUT_COLUMNS).to_csv(out_path, index=False)
        return {"status": "SKIPPED", "reason": "no_lda_data", "rows": 0}

    # Merge RFPs with awards on rfp_id
    if award_df is not None and not award_df.empty:
        merged = rfp_df.merge(
            award_df[["rfp_id", "awarded_vendor", "awarded_vendor_normalized"]],
            on="rfp_id", how="left",
        )
    else:
        merged = rfp_df.copy()
        merged["awarded_vendor"] = ""
        merged["awarded_vendor_normalized"] = ""

    # Parse dates
    merged["posted_dt"] = _parse_dates(merged, "posted_date")

    # Normalize LDA client names
    if "client_name" in lda_df.columns:
        lda_df["client_name_normalized"] = lda_df["client_name"].apply(_normalize_name)
    else:
        lda_df["client_name_normalized"] = ""

    lda_df["filing_date_dt"] = pd.to_datetime(
        lda_df.get("filing_date") or lda_df.get("dt_posted") or lda_df.get("period_of_report"),
        errors="coerce",
    )

    # Cross-reference each RFP
    rows = []
    flagged = 0
    for _, rfp in merged.iterrows():
        posted_dt = rfp.get("posted_dt")
        vendor_norm = str(rfp.get("awarded_vendor_normalized") or "")

        lda_flag = 0
        lobby_lead_days = None
        lda_spend_prior = 0.0
        lda_registrants = ""
        lda_issues = ""
        lda_filings_count = 0

        if vendor_norm and pd.notna(posted_dt):
            matches = _match_vendor_to_lda(vendor_norm, lda_df)
            if not matches.empty:
                window_start = posted_dt - pd.Timedelta(days=window_days)
                prior = matches[
                    matches["filing_date_dt"].between(window_start, posted_dt, inclusive="both")
                ]
                if not prior.empty:
                    lda_flag = 1
                    flagged += 1
                    # Days between most recent filing and RFP posting
                    most_recent = prior["filing_date_dt"].max()
                    lobby_lead_days = int((posted_dt - most_recent).days)
                    # Income sum
                    if "income" in prior.columns:
                        lda_spend_prior = pd.to_numeric(prior["income"], errors="coerce").sum()
                    if "registrant_name" in prior.columns:
                        lda_registrants = "|".join(prior["registrant_name"].dropna().unique()[:5])
                    if "general_issue_code" in prior.columns:
                        lda_issues = "|".join(prior["general_issue_code"].dropna().unique()[:10])
                    lda_filings_count = len(prior)

        # Influence score: flag × (1 / max(lead_days,1)) × log(spend+1)
        import math
        if lda_flag and lobby_lead_days is not None:
            recency = max(1, window_days - lobby_lead_days) / window_days
            spend_weight = math.log1p(lda_spend_prior) / math.log1p(1_000_000)
            influence_score = round(min(1.0, recency * (0.6 + 0.4 * spend_weight)), 4)
        else:
            influence_score = 0.0

        rows.append({
            "rfp_id":                   rfp.get("rfp_id", ""),
            "title":                    rfp.get("title", ""),
            "agency":                   rfp.get("agency", ""),
            "posted_date":              rfp.get("posted_date", ""),
            "due_date":                 rfp.get("due_date", ""),
            "awarded_vendor":           rfp.get("awarded_vendor", ""),
            "awarded_vendor_normalized": vendor_norm,
            "lda_flag":                 lda_flag,
            "lobby_lead_days":          lobby_lead_days if lobby_lead_days is not None else "",
            "lda_spend_prior_window":   round(lda_spend_prior, 2),
            "lda_registrants_prior":    lda_registrants,
            "lda_issues_prior":         lda_issues,
            "lda_filings_prior_count":  lda_filings_count,
            "influence_score":          influence_score,
        })

    df_out = pd.DataFrame(rows, columns=OUTPUT_COLUMNS)
    df_out = df_out.sort_values("influence_score", ascending=False)
    df_out.to_csv(out_path, index=False)

    n = len(df_out)
    logger.info(f"  RFP-lobby crossref: {n:,} RFPs, {flagged:,} with prior lobbying → {out_path.name}")

    return {"status": "OK", "rows": n, "flagged_rfps": flagged}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Cross-reference RFPs with LDA lobbying")
    parser.add_argument("--window-days", type=int, default=WINDOW_DAYS,
                        help=f"Days before RFP posting to search for lobbying (default: {WINDOW_DAYS})")
    args = parser.parse_args()
    result = run(window_days=args.window_days)
    return 0 if result.get("status") in ("OK", "SKIPPED") else 1


if __name__ == "__main__":
    sys.exit(main())
