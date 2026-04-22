"""
Integrated power/influence network analysis for Puerto Rico.

Combines every data source in the pipeline to produce a single ranked
entity list showing which organizations sit at the center of PR's
federal financial ecosystem.

Scoring model — six axes, each normalized 0-100 then weighted:

  1. Federal awards received         (weight 0.35) — contracts + grants + loans
  2. FEC campaign contributions      (weight 0.15) — donations to federal candidates
  3. Lobbying expenditure            (weight 0.15) — LDA client expenses + registrant income
  4. Nonprofit financial size        (weight 0.10) — 990 total revenue
  5. Medicare/CMS payments received  (weight 0.10) — federal healthcare reimbursements
  6. Cross-source presence           (weight 0.15) — bonus for appearing in multiple datasets

Output:
  data/staging/processed/pr_power_network.csv
    One row per unique entity, ranked by composite influence score.
    Columns include all raw values, normalized scores, and composite score.

  data/staging/processed/pr_power_network_summary.json
    Top-level summary statistics and top-50 entity list.

Usage:
  python3 scripts/analyze_power_network.py
  python3 scripts/analyze_power_network.py --top 100
"""

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import numpy as np

from scripts.config import PROCESSED_DIR, PROJECT_ROOT, setup_logging


# ---------------------------------------------------------------------------
# Scoring weights
# ---------------------------------------------------------------------------

WEIGHTS = {
    "awards":    0.35,
    "fec":       0.15,
    "lobbying":  0.15,
    "nonprofit": 0.10,
    "medicare":  0.10,
    "presence":  0.15,
}
assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-9, "Weights must sum to 1"


# ---------------------------------------------------------------------------
# Name normalization
# ---------------------------------------------------------------------------

_STRIP_RE = re.compile(r"[^\w\s]")
_SPACE_RE = re.compile(r"\s+")
_SUFFIXES = {
    "INC", "LLC", "LLP", "CORP", "CO", "LTD", "LP", "PC",
    "PLLC", "DBA", "THE", "AND", "OF", "SA", "SRL",
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
# Min-max normalization to 0–100
# ---------------------------------------------------------------------------

def _minmax(series: pd.Series) -> pd.Series:
    lo, hi = series.min(), series.max()
    if hi == lo:
        return pd.Series(np.where(series > 0, 50.0, 0.0), index=series.index)
    return (series - lo) / (hi - lo) * 100


# ---------------------------------------------------------------------------
# Safe file loader
# ---------------------------------------------------------------------------

def _load(path: Path, logger) -> pd.DataFrame | None:
    if not path.exists():
        logger.info(f"  {path.name}: not found — skipping axis")
        return None
    df = pd.read_csv(path, dtype=str, low_memory=False)
    logger.info(f"  {path.name}: {len(df):,} rows")
    return df


def _num(df: pd.DataFrame, col: str) -> pd.Series:
    if col not in df.columns:
        return pd.Series(0.0, index=df.index)
    return pd.to_numeric(df[col], errors="coerce").fillna(0.0)


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------

def build_power_network(root: Path = None, top_n: int = 50) -> dict:
    if root is None:
        root = PROJECT_ROOT

    root    = Path(root)
    pdir    = root / "data" / "staging" / "processed"
    logger  = setup_logging("analyze_power_network")

    logger.info("Building integrated PR power network...")

    # ------------------------------------------------------------------
    # Axis 1: Federal awards (spine)
    # ------------------------------------------------------------------
    awards_path = pdir / "pr_all_awards_master.csv"
    if not awards_path.exists():
        logger.error("  Awards master missing — run build_unified_master.py first")
        return {"rows": 0, "status": "MISSING_AWARDS"}

    awards = pd.read_csv(awards_path, dtype=str, low_memory=False)
    awards["_norm"]   = awards["recipient_name"].apply(_normalize)
    awards["_amount"] = _num(awards, "obligated_amount")

    spine = (
        awards[awards["_norm"] != ""]
        .groupby("_norm")
        .agg(
            canonical_name         = ("recipient_name",  "first"),
            awards_total           = ("_amount",         "sum"),
            awards_count           = ("award_id",        "nunique"),
            awards_datasets        = ("source_dataset",  lambda x: "|".join(sorted(x.dropna().unique()))),
            awards_fiscal_years    = ("fiscal_year",     lambda x: _yr_range(x)),
        )
        .reset_index()
        .rename(columns={"_norm": "norm_key"})
    )
    logger.info(f"  Awards spine: {len(spine):,} unique entities")

    # ------------------------------------------------------------------
    # Axis 2: FEC contributions
    # ------------------------------------------------------------------
    fec_xref = _load(pdir / "pr_fec_crossref.csv", logger)
    if fec_xref is not None and not fec_xref.empty:
        fec_xref["norm_key"] = fec_xref.get("normalized_name",
                               fec_xref.get("fec_contributor_name", pd.Series(dtype=str))).apply(_normalize)
        fec_agg = (
            fec_xref.groupby("norm_key")
            .agg(fec_total_contributions=("total_contributions", "sum"))
            .reset_index()
        )
        fec_agg["fec_total_contributions"] = pd.to_numeric(
            fec_agg["fec_total_contributions"], errors="coerce").fillna(0)
    else:
        fec_agg = None

    # ------------------------------------------------------------------
    # Axis 3: LDA lobbying
    # ------------------------------------------------------------------
    lda_xref = _load(pdir / "pr_lobbying_crossref.csv", logger)
    if lda_xref is not None and not lda_xref.empty:
        lda_xref["norm_key"] = lda_xref.get("normalized_name",
                               lda_xref.get("lda_client_name", pd.Series(dtype=str))).apply(_normalize)
        lda_agg = (
            lda_xref.groupby("norm_key")
            .agg(
                lda_client_expenses   = ("total_client_expenses",   "sum"),
                lda_registrant_income = ("total_registrant_income", "sum"),
                lda_filing_count      = ("filing_count",            "sum"),
            )
            .reset_index()
        )
        for col in ["lda_client_expenses", "lda_registrant_income"]:
            lda_agg[col] = pd.to_numeric(lda_agg[col], errors="coerce").fillna(0)
        lda_agg["lda_lobbying_total"] = lda_agg["lda_client_expenses"] + lda_agg["lda_registrant_income"]
    else:
        lda_agg = None

    # ------------------------------------------------------------------
    # Axis 4: Nonprofit 990 data
    # ------------------------------------------------------------------
    df_990 = _load(pdir / "pr_nonprofits.csv", logger)
    if df_990 is not None and not df_990.empty:
        df_990["norm_key"] = df_990["name"].apply(_normalize)
        np_agg = (
            df_990.drop_duplicates("norm_key")
            [["norm_key", "ein", "ntee_category", "total_revenue", "total_assets",
              "grants_paid", "revenue_trend"]]
            .copy()
        )
        for col in ["total_revenue", "total_assets", "grants_paid"]:
            np_agg[col] = pd.to_numeric(np_agg[col], errors="coerce").fillna(0)
        np_agg = np_agg.rename(columns={
            "total_revenue": "np_revenue",
            "total_assets":  "np_assets",
            "grants_paid":   "np_grants_paid",
            "revenue_trend": "np_revenue_trend",
        })
    else:
        np_agg = None

    # ------------------------------------------------------------------
    # Axis 5: CMS Medicare payments
    # ------------------------------------------------------------------
    df_cms = _load(pdir / "pr_cms_medicare_providers.csv", logger)
    if df_cms is not None and not df_cms.empty:
        name_parts = []
        for c in ["provider_last_name", "provider_first_name"]:
            df_cms[c] = df_cms.get(c, pd.Series(dtype=str)).fillna("")
        df_cms["_full"] = (df_cms["provider_last_name"] + " " + df_cms["provider_first_name"]).str.strip()
        df_cms["norm_key"] = df_cms["_full"].apply(_normalize)
        cms_agg = (
            df_cms[df_cms["norm_key"] != ""]
            .drop_duplicates("norm_key")
            [["norm_key", "provider_type", "total_medicare_payment", "total_unique_benes"]]
            .copy()
        )
        for col in ["total_medicare_payment", "total_unique_benes"]:
            cms_agg[col] = pd.to_numeric(cms_agg[col], errors="coerce").fillna(0)
        cms_agg = cms_agg.rename(columns={
            "total_medicare_payment": "cms_medicare_payment",
            "total_unique_benes":     "cms_patient_count",
        })
    else:
        cms_agg = None

    # ------------------------------------------------------------------
    # Merge all axes onto spine
    # ------------------------------------------------------------------
    merged = spine.copy()
    sources_present = {"awards"}

    if fec_agg is not None:
        merged = merged.merge(fec_agg, on="norm_key", how="left")
        sources_present.add("fec")
    else:
        merged["fec_total_contributions"] = 0.0

    if lda_agg is not None:
        merged = merged.merge(lda_agg, on="norm_key", how="left")
        sources_present.add("lda")
    else:
        merged["lda_lobbying_total"] = 0.0

    if np_agg is not None:
        merged = merged.merge(np_agg, on="norm_key", how="left")
        sources_present.add("nonprofit")
    else:
        merged["np_revenue"] = 0.0

    if cms_agg is not None:
        merged = merged.merge(cms_agg, on="norm_key", how="left")
        sources_present.add("medicare")
    else:
        merged["cms_medicare_payment"] = 0.0

    # Fill numeric NaN
    for col in ["fec_total_contributions", "lda_lobbying_total",
                "np_revenue", "cms_medicare_payment"]:
        if col in merged.columns:
            merged[col] = pd.to_numeric(merged[col], errors="coerce").fillna(0.0)
        else:
            merged[col] = 0.0

    # ------------------------------------------------------------------
    # Cross-source presence score (0–5 = number of datasets entity appears in)
    # ------------------------------------------------------------------
    merged["source_presence"] = (
        (merged["awards_total"] > 0).astype(int) +
        (merged.get("fec_total_contributions", pd.Series([0]*len(merged))).fillna(0) > 0).astype(int) +
        (merged.get("lda_lobbying_total",       pd.Series([0]*len(merged))).fillna(0) > 0).astype(int) +
        (merged.get("np_revenue",               pd.Series([0]*len(merged))).fillna(0) > 0).astype(int) +
        (merged.get("cms_medicare_payment",     pd.Series([0]*len(merged))).fillna(0) > 0).astype(int)
    )

    # ------------------------------------------------------------------
    # Normalize each axis and compute composite score
    # ------------------------------------------------------------------
    merged["score_awards"]    = _minmax(merged["awards_total"])
    merged["score_fec"]       = _minmax(merged.get("fec_total_contributions", pd.Series([0]*len(merged))).fillna(0))
    merged["score_lobbying"]  = _minmax(merged.get("lda_lobbying_total", pd.Series([0]*len(merged))).fillna(0))
    merged["score_nonprofit"] = _minmax(merged.get("np_revenue", pd.Series([0]*len(merged))).fillna(0))
    merged["score_medicare"]  = _minmax(merged.get("cms_medicare_payment", pd.Series([0]*len(merged))).fillna(0))
    merged["score_presence"]  = merged["source_presence"] / 5 * 100

    merged["influence_score"] = (
        merged["score_awards"]    * WEIGHTS["awards"] +
        merged["score_fec"]       * WEIGHTS["fec"] +
        merged["score_lobbying"]  * WEIGHTS["lobbying"] +
        merged["score_nonprofit"] * WEIGHTS["nonprofit"] +
        merged["score_medicare"]  * WEIGHTS["medicare"] +
        merged["score_presence"]  * WEIGHTS["presence"]
    ).round(2)

    merged = merged.sort_values("influence_score", ascending=False).reset_index(drop=True)
    merged.insert(0, "rank", merged.index + 1)

    # ------------------------------------------------------------------
    # Write outputs
    # ------------------------------------------------------------------
    net_path = pdir / "pr_power_network.csv"
    merged.to_csv(net_path, index=False, encoding="utf-8")
    logger.info(f"  Written: {net_path.name} ({len(merged):,} entities)")

    # Summary JSON
    top_entities = []
    for _, row in merged.head(top_n).iterrows():
        entry = {
            "rank":            int(row["rank"]),
            "name":            str(row["canonical_name"]),
            "influence_score": float(row["influence_score"]),
            "awards_total":    float(row["awards_total"]),
            "source_presence": int(row["source_presence"]),
            "sources":         [],
        }
        if row["awards_total"] > 0:           entry["sources"].append("awards")
        if row.get("fec_total_contributions", 0) > 0: entry["sources"].append("fec")
        if row.get("lda_lobbying_total", 0) > 0:      entry["sources"].append("lda")
        if row.get("np_revenue", 0) > 0:              entry["sources"].append("nonprofit_990")
        if row.get("cms_medicare_payment", 0) > 0:    entry["sources"].append("medicare")
        top_entities.append(entry)

    total_awards_val = float(merged["awards_total"].sum())
    multi_source     = int((merged["source_presence"] >= 2).sum())
    loop_entities    = int((
        (merged.get("fec_total_contributions", 0) > 0) &
        (merged.get("lda_lobbying_total", 0) > 0) &
        (merged["awards_total"] > 0)
    ).sum())

    summary = {
        "total_entities":     len(merged),
        "total_awards_usd":   total_awards_val,
        "multi_source_count": multi_source,
        "full_loop_count":    loop_entities,
        "sources_included":   sorted(sources_present),
        "score_weights":      WEIGHTS,
        "top_entities":       top_entities,
    }

    summary_path = pdir / "pr_power_network_summary.json"
    with open(summary_path, "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2)
    logger.info(f"  Written: {summary_path.name}")

    # ------------------------------------------------------------------
    # Log summary
    # ------------------------------------------------------------------
    logger.info("=" * 60)
    logger.info("PR POWER NETWORK SUMMARY")
    logger.info("=" * 60)
    logger.info(f"  Total entities ranked:       {len(merged):,}")
    logger.info(f"  Multi-source (≥2 datasets):  {multi_source:,}")
    logger.info(f"  Full-loop entities           {loop_entities:,}")
    logger.info(f"    (awards + FEC + lobbying)")
    logger.info(f"  Total federal awards:        ${total_awards_val:,.0f}")
    logger.info(f"  Data sources included:       {', '.join(sorted(sources_present))}")
    logger.info(f"\n  Score weights: " +
                ", ".join(f"{k}={v:.0%}" for k, v in WEIGHTS.items()))
    logger.info(f"\n  TOP 20 ENTITIES BY INFLUENCE SCORE:")
    logger.info(f"  {'Rank':<5} {'Score':>6}  {'Entity':<52}  {'Awards':>14}  Src")
    logger.info(f"  {'-'*4} {'-'*6}  {'-'*52}  {'-'*14}  ---")
    for _, row in merged.head(20).iterrows():
        sources = []
        if row.get("fec_total_contributions", 0) > 0: sources.append("F")
        if row.get("lda_lobbying_total", 0) > 0:      sources.append("L")
        if row.get("np_revenue", 0) > 0:              sources.append("N")
        if row.get("cms_medicare_payment", 0) > 0:    sources.append("M")
        src_str = "".join(sources) or "·"
        logger.info(
            f"  {int(row['rank']):<5} {row['influence_score']:>6.1f}  "
            f"{str(row['canonical_name'])[:52]:<52}  "
            f"${float(row['awards_total']):>13,.0f}  {src_str}"
        )
    logger.info("  (F=FEC  L=Lobbying  N=Nonprofit  M=Medicare)")

    return {
        "rows":           len(merged),
        "multi_source":   multi_source,
        "full_loop":      loop_entities,
        "status":         "OK",
        "network_path":   str(net_path),
        "summary_path":   str(summary_path),
    }


def _yr_range(series: pd.Series) -> str:
    vals = pd.to_numeric(series, errors="coerce").dropna()
    if vals.empty:
        return ""
    lo, hi = int(vals.min()), int(vals.max())
    return str(lo) if lo == hi else f"{lo}-{hi}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Build PR integrated power network analysis")
    parser.add_argument("--top", type=int, default=50,
                        help="Number of top entities to include in summary JSON (default: 50)")
    args = parser.parse_args()
    result = build_power_network(top_n=args.top)
    print(f"\nPower network complete: {result['rows']:,} entities ranked, "
          f"{result['full_loop']:,} full-loop entities → {result.get('network_path', '')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
