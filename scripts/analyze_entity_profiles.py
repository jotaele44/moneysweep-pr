"""
Build enriched entity profiles by cross-referencing the unified awards master
against three supplementary financial datasets:

  1. IRS 990 nonprofits (pr_nonprofits.csv)
     → which award recipients are nonprofits, their revenue/asset size
  2. CMS Medicare providers (pr_cms_medicare_providers.csv)
     → which award recipients also bill Medicare
  3. FDIC bank institutions (pr_fdic_institutions.csv)
     → which award recipients are federally-insured banks

Additionally surfaces entities present in these datasets that are NOT
yet in the awards master — potential gaps in federal spending coverage.

Matching is done on normalized entity names.

Output:
  data/staging/processed/pr_entity_profiles.csv
    One row per unique entity in the awards master, enriched with columns
    from each supplementary source where a name match exists.

  data/staging/processed/pr_entity_gaps.csv
    Entities in the supplementary sources NOT matched in the awards master,
    ranked by financial size — candidates for manual review.

Usage:
  python3 scripts/analyze_entity_profiles.py
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from scripts.config import PROCESSED_DIR, PROJECT_ROOT, setup_logging


# ---------------------------------------------------------------------------
# Name normalization (shared with FEC and LDA crossref)
# ---------------------------------------------------------------------------

_STRIP_RE = re.compile(r"[^\w\s]")
_SPACE_RE = re.compile(r"\s+")
_SUFFIXES = {
    "INC", "LLC", "LLP", "CORP", "CO", "LTD", "LP", "PC",
    "PLLC", "DBA", "THE", "AND", "OF", "SA", "SRL",
    "HOSPITAL", "HEALTH", "CENTER", "CENTRE",  # common in both sides
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
# Helpers
# ---------------------------------------------------------------------------

def _safe_load(path: Path, logger) -> pd.DataFrame | None:
    if not path.exists():
        logger.warning(f"  Not found: {path.name} — skipping")
        return None
    try:
        df = pd.read_csv(path, dtype=str, low_memory=False)
        logger.info(f"  Loaded {path.name}: {len(df):,} rows")
        return df
    except Exception as exc:
        logger.error(f"  Failed to load {path.name}: {exc}")
        return None


def _sum_col(df: pd.DataFrame, col: str) -> float:
    if col not in df.columns:
        return 0.0
    return pd.to_numeric(df[col], errors="coerce").fillna(0).sum()


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------

def build_profiles(root: Path = None) -> dict:
    if root is None:
        root = PROJECT_ROOT

    root          = Path(root)
    processed_dir = root / "data" / "staging" / "processed"
    logger        = setup_logging("analyze_entity_profiles")

    # ------------------------------------------------------------------
    # Load awards master — the spine
    # ------------------------------------------------------------------
    awards_path = processed_dir / "pr_all_awards_master.csv"
    if not awards_path.exists():
        logger.error(f"  Awards master not found — run build_unified_master.py first")
        return {"rows": 0, "status": "MISSING_AWARDS"}

    logger.info("Loading awards master...")
    awards = pd.read_csv(awards_path, dtype=str, low_memory=False)
    logger.info(f"  {len(awards):,} award rows")

    awards["_norm"]  = awards["recipient_name"].apply(_normalize)
    awards["_amount"] = pd.to_numeric(awards["obligated_amount"], errors="coerce").fillna(0)

    entity_spine = (
        awards[awards["_norm"] != ""]
        .groupby("_norm")
        .agg(
            recipient_name         = ("recipient_name",  "first"),
            total_awards_obligated = ("_amount",         "sum"),
            award_count            = ("award_id",        "nunique"),
            award_datasets         = ("source_dataset",  lambda x: "|".join(sorted(x.dropna().unique()))),
            fiscal_year_range      = ("fiscal_year",     lambda x: _yr_range(x)),
        )
        .reset_index()
        .rename(columns={"_norm": "normalized_name"})
    )
    logger.info(f"  {len(entity_spine):,} unique award recipients")

    # ------------------------------------------------------------------
    # Load supplementary sources
    # ------------------------------------------------------------------
    df_990    = _safe_load(processed_dir / "pr_nonprofits.csv",               logger)
    df_med    = _safe_load(processed_dir / "pr_cms_medicare_providers.csv",   logger)
    df_banks  = _safe_load(processed_dir / "pr_fdic_institutions.csv",        logger)

    # ------------------------------------------------------------------
    # Build normalized indexes for each source
    # ------------------------------------------------------------------
    gap_rows = []

    # --- 990 nonprofits ---
    if df_990 is not None and not df_990.empty:
        df_990["_norm"] = df_990["name"].apply(_normalize)
        np_index = (
            df_990[df_990["_norm"] != ""]
            .drop_duplicates("_norm")
            [["_norm", "ein", "name", "ntee_code", "ntee_category",
              "subsection_code", "total_revenue", "total_assets",
              "grants_paid", "officer_compensation", "revenue_trend"]]
            .rename(columns={
                "name":               "np_name",
                "ein":                "np_ein",
                "ntee_code":          "np_ntee_code",
                "ntee_category":      "np_ntee_category",
                "subsection_code":    "np_subsection",
                "total_revenue":      "np_total_revenue",
                "total_assets":       "np_total_assets",
                "grants_paid":        "np_grants_paid",
                "officer_compensation": "np_officer_comp",
                "revenue_trend":      "np_revenue_trend",
            })
        )

        # Gap: nonprofits NOT in awards master
        np_unmatched = np_index[~np_index["_norm"].isin(entity_spine["normalized_name"])].copy()
        np_unmatched["_source"] = "990_nonprofit"
        np_unmatched["_size"]   = pd.to_numeric(np_unmatched["np_total_revenue"], errors="coerce").fillna(0)
        gap_rows.append(np_unmatched[["_norm", "_source", "_size",
                                       "np_name", "np_ntee_category"]].rename(
            columns={"_norm": "normalized_name", "np_name": "entity_name",
                     "np_ntee_category": "entity_category"}))
    else:
        np_index = pd.DataFrame(columns=["_norm"])

    # --- Medicare providers ---
    if df_med is not None and not df_med.empty:
        name_col = None
        for c in ["provider_last_name", "provider_first_name"]:
            if c not in df_med.columns:
                df_med[c] = ""
        df_med["_full_name"] = (
            df_med.get("provider_last_name", pd.Series(dtype=str)).fillna("") + " " +
            df_med.get("provider_first_name", pd.Series(dtype=str)).fillna("")
        ).str.strip()
        df_med["_norm"] = df_med["_full_name"].apply(_normalize)

        med_index = (
            df_med[df_med["_norm"] != ""]
            .drop_duplicates("_norm")
            [["_norm", "_full_name", "provider_type",
              "total_medicare_payment", "total_services", "total_unique_benes"]]
            .rename(columns={
                "_full_name":           "med_provider_name",
                "provider_type":        "med_provider_type",
                "total_medicare_payment": "med_total_payment",
                "total_services":       "med_total_services",
                "total_unique_benes":   "med_total_benes",
            })
        )

        med_unmatched = med_index[~med_index["_norm"].isin(entity_spine["normalized_name"])].copy()
        med_unmatched["_source"] = "cms_medicare"
        med_unmatched["_size"]   = pd.to_numeric(med_unmatched["med_total_payment"], errors="coerce").fillna(0)
        gap_rows.append(med_unmatched[["_norm", "_source", "_size",
                                        "med_provider_name", "med_provider_type"]].rename(
            columns={"_norm": "normalized_name", "med_provider_name": "entity_name",
                     "med_provider_type": "entity_category"}))
    else:
        med_index = pd.DataFrame(columns=["_norm"])

    # --- FDIC banks ---
    if df_banks is not None and not df_banks.empty:
        df_banks["_norm"] = df_banks["name"].apply(_normalize)
        bank_index = (
            df_banks[df_banks["_norm"] != ""]
            .drop_duplicates("_norm")
            [["_norm", "name", "city", "active", "total_assets",
              "total_deposits", "net_income", "tier1_capital_ratio"]]
            .rename(columns={
                "name":               "bank_name",
                "active":             "bank_active",
                "total_assets":       "bank_total_assets",
                "total_deposits":     "bank_total_deposits",
                "net_income":         "bank_net_income",
                "tier1_capital_ratio": "bank_tier1_ratio",
            })
        )

        bank_unmatched = bank_index[~bank_index["_norm"].isin(entity_spine["normalized_name"])].copy()
        bank_unmatched["_source"] = "fdic_bank"
        bank_unmatched["_size"]   = pd.to_numeric(bank_unmatched["bank_total_assets"], errors="coerce").fillna(0)
        gap_rows.append(bank_unmatched[["_norm", "_source", "_size",
                                         "bank_name"]].rename(
            columns={"_norm": "normalized_name", "bank_name": "entity_name"}).assign(entity_category="bank"))
    else:
        bank_index = pd.DataFrame(columns=["_norm"])

    # ------------------------------------------------------------------
    # Join all sources onto entity spine
    # ------------------------------------------------------------------
    merged = entity_spine.copy()

    if not np_index.empty and "_norm" in np_index.columns:
        merged = merged.merge(
            np_index.rename(columns={"_norm": "normalized_name"}),
            on="normalized_name", how="left"
        )
    if not med_index.empty and "_norm" in med_index.columns:
        merged = merged.merge(
            med_index.rename(columns={"_norm": "normalized_name"}),
            on="normalized_name", how="left"
        )
    if not bank_index.empty and "_norm" in bank_index.columns:
        merged = merged.merge(
            bank_index.rename(columns={"_norm": "normalized_name"}),
            on="normalized_name", how="left"
        )

    # Derived flags
    merged["is_nonprofit"] = merged.get("np_ein", pd.Series(dtype=str)).notna() & \
                             (merged.get("np_ein", pd.Series(dtype=str)) != "")
    merged["is_medicare_provider"] = merged.get("med_total_payment", pd.Series(dtype=str)).notna() & \
                                     (merged.get("med_total_payment", pd.Series(dtype=str)) != "")
    merged["is_fdic_bank"] = merged.get("bank_name", pd.Series(dtype=str)).notna() & \
                             (merged.get("bank_name", pd.Series(dtype=str)) != "")

    merged = merged.sort_values("total_awards_obligated", ascending=False)

    # Write entity profiles
    profiles_path = processed_dir / "pr_entity_profiles.csv"
    merged.to_csv(profiles_path, index=False, encoding="utf-8")
    logger.info(f"  Written: {profiles_path.name} ({len(merged):,} entities)")

    # ------------------------------------------------------------------
    # Write gap file
    # ------------------------------------------------------------------
    gaps_path = processed_dir / "pr_entity_gaps.csv"
    if gap_rows:
        df_gaps = pd.concat(gap_rows, ignore_index=True)
        df_gaps = df_gaps.sort_values("_size", ascending=False)
        df_gaps.to_csv(gaps_path, index=False, encoding="utf-8")
        logger.info(f"  Written: {gaps_path.name} ({len(df_gaps):,} unmatched entities)")
    else:
        pd.DataFrame(columns=["normalized_name", "_source", "_size",
                               "entity_name", "entity_category"]).to_csv(gaps_path, index=False)

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    def _flag_col(name):
        col = merged.get(name)
        if col is None or not isinstance(col, pd.Series):
            return pd.Series([False] * len(merged), index=merged.index, dtype=bool)
        return col.fillna(False).astype(bool)

    flag_np   = _flag_col("is_nonprofit")
    flag_med  = _flag_col("is_medicare_provider")
    flag_bank = _flag_col("is_fdic_bank")

    np_matched   = int(flag_np.sum())
    med_matched  = int(flag_med.sum())
    bank_matched = int(flag_bank.sum())
    multi_match  = int(((flag_np.astype(int) + flag_med.astype(int) + flag_bank.astype(int)) >= 2).sum())

    total_awards = float(merged["total_awards_obligated"].sum())
    np_awards    = float(pd.to_numeric(merged.loc[flag_np, "total_awards_obligated"],
                                       errors="coerce").sum()) if np_matched else 0
    med_awards   = float(pd.to_numeric(merged.loc[flag_med, "total_awards_obligated"],
                                       errors="coerce").sum()) if med_matched else 0

    logger.info("=" * 60)
    logger.info("ENTITY PROFILE SUMMARY")
    logger.info("=" * 60)
    logger.info(f"  Total award entities profiled:   {len(merged):,}")
    logger.info(f"  Matched as nonprofit (990):      {np_matched:,}  (${np_awards:,.0f} in awards)")
    logger.info(f"  Matched as Medicare provider:    {med_matched:,}  (${med_awards:,.0f} in awards)")
    logger.info(f"  Matched as FDIC bank:            {bank_matched:,}")
    logger.info(f"  Match in 2+ sources:             {multi_match:,}")
    logger.info(f"  Entities in supp. sources only:  {len(df_gaps) if gap_rows else 0:,}")

    logger.info(f"\n  Top 10 by awards — with supplementary source flags:")
    for _, row in merged.head(10).iterrows():
        flags = []
        if row.get("is_nonprofit")  is True or row.get("is_nonprofit")  == True:  flags.append("990")
        if row.get("is_medicare_provider") is True or row.get("is_medicare_provider") == True: flags.append("CMS")
        if row.get("is_fdic_bank") is True or row.get("is_fdic_bank") == True: flags.append("FDIC")
        flag_str = "[" + "|".join(flags) + "]" if flags else ""
        name  = str(row["recipient_name"])[:50]
        award = float(row["total_awards_obligated"])
        logger.info(f"    {name:<50}  ${award:>14,.0f}  {flag_str}")

    return {
        "rows":         len(merged),
        "gap_rows":     len(df_gaps) if gap_rows else 0,
        "np_matched":   np_matched,
        "med_matched":  med_matched,
        "bank_matched": bank_matched,
        "status":       "OK",
        "profiles_path": str(profiles_path),
        "gaps_path":    str(gaps_path),
    }


def _yr_range(series: pd.Series) -> str:
    vals = pd.to_numeric(series, errors="coerce").dropna()
    if vals.empty:
        return ""
    lo, hi = int(vals.min()), int(vals.max())
    return str(lo) if lo == hi else f"{lo}-{hi}"


def main() -> int:
    result = build_profiles()
    print(f"\nEntity profiles complete: {result['rows']:,} entities profiled, "
          f"{result['gap_rows']:,} gap entities → {result.get('profiles_path', '')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
