"""
Build a unified awards master CSV from all individual dataset masters.

Reads pr_contracts_master.csv (legacy schema) and all new canonical-schema
masters, normalizes them to a single canonical schema, deduplicates within
each source dataset, and writes:
  - data/staging/processed/pr_all_awards_master.csv
  - data/staging/processed/pr_all_awards_summary.json

Usage:
  python3 scripts/build_unified_master.py          # build unified master
  python3 scripts/build_unified_master.py --force  # rebuild even if exists
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.config import PROJECT_ROOT, PROCESSED_DIR, setup_logging
import pandas as pd
import argparse
import json


# ---------------------------------------------------------------------------
# Canonical column order
# ---------------------------------------------------------------------------

CANONICAL_COLUMNS = [
    "award_id",
    "recipient_name",
    "recipient_uei",
    "awarding_agency",
    "awarding_sub_agency",
    "obligated_amount",
    "award_date",
    "fiscal_year",
    "pop_state",
    "pop_county",
    "description",
    "source_file",
    "source_dataset",
    "award_category",
]

# ---------------------------------------------------------------------------
# New dataset masters (already in canonical schema)
# ---------------------------------------------------------------------------

NEW_MASTERS = [
    ("pr_grants_master.csv",    "grants"),
    ("pr_subawards_master.csv", "subawards"),
    ("pr_fema_pa_master.csv",   "fema_pa"),
    ("pr_fema_hmgp_master.csv", "fema_hmgp"),
    ("pr_research_master.csv",  "research"),
    ("pr_sba_loans_master.csv", "sba_loans"),
    ("pr_slfrf_master.csv",     "slfrf"),
    ("pr_cdbg_dr_master.csv",   "cdbg_dr"),
    ("pr_dot_master.csv",       "dot"),
    ("pr_usda_master.csv",      "usda"),
    ("pr_doe_master.csv",       "doe"),
    ("pr_hud_master.csv",       "hud"),
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_POP_STATE_MAP = {
    "puerto rico": "PR",
    "72": "PR",
}


def _standardize_pop_state(series: pd.Series) -> pd.Series:
    """Normalize pop_state: 'Puerto Rico' → 'PR', '72' → 'PR'. Others unchanged."""
    def _norm(val):
        if pd.isna(val) or str(val).strip() == "":
            return val
        lowered = str(val).strip().lower()
        return _POP_STATE_MAP.get(lowered, str(val).strip())
    return series.map(_norm)


def _derive_fiscal_year(date_series: pd.Series) -> pd.Series:
    """
    Derive US federal fiscal year from a date series.
    Oct/Nov/Dec → year + 1, otherwise → year.
    Returns a string series of 4-digit years.
    """
    dates = pd.to_datetime(date_series, errors="coerce")
    fy = dates.apply(
        lambda d: str(d.year + 1) if (not pd.isna(d) and d.month >= 10) else (str(d.year) if not pd.isna(d) else "")
    )
    return fy


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

def run(root=None) -> dict:
    """
    Build the unified awards master. Returns a summary dict.

    Parameters
    ----------
    root : Path or None
        Project root directory. Defaults to PROJECT_ROOT from config.
    """
    if root is None:
        root = PROJECT_ROOT

    root = Path(root)
    processed_dir = root / "data" / "staging" / "processed"
    logger = setup_logging("build_unified_master", log_dir=root / "data" / "logs")

    frames = []

    # ------------------------------------------------------------------
    # 1. Read pr_contracts_master.csv and remap to canonical schema
    # ------------------------------------------------------------------
    contracts_path = processed_dir / "pr_contracts_master.csv"
    if contracts_path.exists():
        logger.info(f"  Reading contracts master: {contracts_path.name}")
        try:
            df_c = pd.read_csv(contracts_path, dtype=str, low_memory=False)
            # Remap legacy columns → canonical
            df_canon = pd.DataFrame()
            df_canon["award_id"]          = df_c.get("contract_id", pd.Series(dtype=str))
            df_canon["recipient_name"]    = df_c.get("vendor_name",  pd.Series(dtype=str))
            df_canon["awarding_agency"]   = df_c.get("agency_name",  pd.Series(dtype=str))
            df_canon["award_date"]        = df_c.get("award_date",   pd.Series(dtype=str))
            df_canon["obligated_amount"]  = df_c.get("obligated_amount", pd.Series(dtype=str))
            df_canon["pop_state"]         = df_c.get("pop_state",    pd.Series(dtype=str))
            df_canon["source_file"]       = df_c.get("source_file",  pd.Series(dtype=str))
            df_canon["fiscal_year"]       = df_c.get("fiscal_year",  pd.Series(dtype=str))
            # Fixed values
            df_canon["source_dataset"]    = "contracts"
            df_canon["award_category"]    = "contract"
            # Blank placeholders
            df_canon["recipient_uei"]     = ""
            df_canon["awarding_sub_agency"] = ""
            df_canon["pop_county"]        = ""
            df_canon["description"]       = ""

            # ----------------------------------------------------------
            # 2. Try to enrich recipient_uei from master_enriched.csv
            # ----------------------------------------------------------
            enriched_path = processed_dir / "enrichment" / "master_enriched.csv"
            if enriched_path.exists():
                logger.info(f"  Joining UEI enrichment from {enriched_path.name}")
                try:
                    df_enriched = pd.read_csv(enriched_path, dtype=str, low_memory=False)
                    # Normalize column names
                    df_enriched.columns = [c.strip().lower() for c in df_enriched.columns]
                    # Look for a uei column — try common names
                    uei_col = None
                    for candidate in ("uei", "recipient_uei", "sam_uei", "entity_uei"):
                        if candidate in df_enriched.columns:
                            uei_col = candidate
                            break
                    # Look for a vendor name column
                    vname_col = None
                    for candidate in ("vendor_name", "recipient_name", "vendorname"):
                        if candidate in df_enriched.columns:
                            vname_col = candidate
                            break
                    if uei_col and vname_col:
                        uei_map = (
                            df_enriched[[vname_col, uei_col]]
                            .dropna(subset=[vname_col, uei_col])
                            .drop_duplicates(subset=[vname_col])
                            .set_index(vname_col)[uei_col]
                        )
                        df_canon["recipient_uei"] = (
                            df_canon["recipient_name"].map(uei_map).fillna("")
                        )
                        resolved = (df_canon["recipient_uei"] != "").sum()
                        logger.info(f"  UEI enrichment: {resolved:,} of {len(df_canon):,} rows resolved")
                    else:
                        logger.warning(
                            f"  master_enriched.csv found but missing expected columns "
                            f"(uei_col={uei_col}, vname_col={vname_col}) — skipping UEI join"
                        )
                except Exception as exc:
                    logger.warning(f"  UEI enrichment join failed: {exc} — continuing without UEI")

            logger.info(f"  Contracts: {len(df_canon):,} rows")
            frames.append(df_canon)
        except Exception as exc:
            logger.error(f"  Failed to read contracts master: {exc}")
    else:
        logger.warning(f"  Contracts master not found: {contracts_path} — skipping")

    # ------------------------------------------------------------------
    # 3. Read each new canonical master if it exists
    # ------------------------------------------------------------------
    for filename, dataset_label in NEW_MASTERS:
        fpath = processed_dir / filename
        if not fpath.exists():
            logger.info(f"  {filename} not found — skipping")
            continue
        try:
            df_new = pd.read_csv(fpath, dtype=str, low_memory=False)
            logger.info(f"  {filename}: {len(df_new):,} rows")
            frames.append(df_new)
        except Exception as exc:
            logger.error(f"  Failed to read {filename}: {exc} — skipping")

    # ------------------------------------------------------------------
    # 4. Concatenate all frames
    # ------------------------------------------------------------------
    if not frames:
        logger.warning("  No data frames loaded — writing empty unified master")
        unified = pd.DataFrame(columns=CANONICAL_COLUMNS)
    else:
        unified = pd.concat(frames, ignore_index=True, sort=False)

    # Ensure all canonical columns exist (fill missing with empty string)
    for col in CANONICAL_COLUMNS:
        if col not in unified.columns:
            unified[col] = ""
    unified = unified[CANONICAL_COLUMNS]

    # ------------------------------------------------------------------
    # 5. Deduplicate within each source_dataset by award_id (keep first)
    # ------------------------------------------------------------------
    before_dedup = len(unified)
    parts = []
    for dataset, group_df in unified.groupby("source_dataset", sort=False):
        deduped = group_df.drop_duplicates(subset=["award_id"], keep="first")
        parts.append(deduped)
    unified = pd.concat(parts, ignore_index=True) if parts else unified
    after_dedup = len(unified)
    removed = before_dedup - after_dedup
    if removed:
        logger.info(f"  Deduplication: removed {removed:,} within-dataset duplicates ({after_dedup:,} rows remain)")

    # ------------------------------------------------------------------
    # 6. Standardize pop_state
    # ------------------------------------------------------------------
    unified["pop_state"] = _standardize_pop_state(unified["pop_state"])

    # ------------------------------------------------------------------
    # 7. Standardize fiscal_year (derive from award_date where missing/null)
    # ------------------------------------------------------------------
    missing_fy_mask = unified["fiscal_year"].isna() | (unified["fiscal_year"].str.strip() == "")
    if missing_fy_mask.any():
        derived = _derive_fiscal_year(unified.loc[missing_fy_mask, "award_date"])
        unified.loc[missing_fy_mask, "fiscal_year"] = derived.values
        logger.info(f"  Derived fiscal_year for {missing_fy_mask.sum():,} rows")

    # ------------------------------------------------------------------
    # 8. Write unified master CSV
    # ------------------------------------------------------------------
    processed_dir.mkdir(parents=True, exist_ok=True)
    output_path = processed_dir / "pr_all_awards_master.csv"
    unified.to_csv(output_path, index=False, encoding="utf-8")
    logger.info(f"  Written: {output_path} ({len(unified):,} rows)")

    # ------------------------------------------------------------------
    # 9. Build summary
    # ------------------------------------------------------------------
    # Convert obligated_amount to numeric for aggregation
    unified["_amount_num"] = pd.to_numeric(unified["obligated_amount"], errors="coerce").fillna(0.0)

    total_rows = len(unified)
    total_obligation = float(unified["_amount_num"].sum())
    unique_recipients = int(unified["recipient_name"].dropna().nunique())

    by_dataset = {}
    for ds, grp in unified.groupby("source_dataset", sort=False):
        by_dataset[str(ds)] = {
            "rows": int(len(grp)),
            "total_obligation": float(grp["_amount_num"].sum()),
        }

    by_fiscal_year = {}
    for fy, grp in unified.groupby("fiscal_year", sort=False):
        fy_str = str(fy).strip()
        if fy_str:
            by_fiscal_year[fy_str] = int(len(grp))
    # Sort by fiscal year key
    by_fiscal_year = dict(sorted(by_fiscal_year.items()))

    summary = {
        "total_rows": total_rows,
        "total_obligation_usd": total_obligation,
        "by_dataset": by_dataset,
        "by_fiscal_year": by_fiscal_year,
        "unique_recipients": unique_recipients,
        "outputs": {
            "unified_master": str(output_path),
        },
    }

    # ------------------------------------------------------------------
    # 10. Write summary JSON
    # ------------------------------------------------------------------
    summary_path = processed_dir / "pr_all_awards_summary.json"
    with open(summary_path, "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2)
    logger.info(f"  Written: {summary_path}")

    # Clean up temporary column
    unified.drop(columns=["_amount_num"], inplace=True, errors="ignore")

    logger.info(
        f"  Unified master complete: {total_rows:,} rows, "
        f"{len(by_dataset)} datasets, "
        f"{unique_recipients:,} unique recipients, "
        f"${total_obligation:,.2f} total obligation"
    )

    return summary


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build unified awards master CSV from all dataset masters."
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Rebuild even if pr_all_awards_master.csv already exists",
    )
    args = parser.parse_args()

    root = PROJECT_ROOT
    processed_dir = root / "data" / "staging" / "processed"
    logger = setup_logging("build_unified_master")

    output_path = processed_dir / "pr_all_awards_master.csv"
    if output_path.exists() and not args.force:
        logger.info(
            f"Unified master already exists: {output_path}\n"
            "Use --force to rebuild."
        )
        return 0

    logger.info("Building unified awards master...")
    summary = run(root=root)
    logger.info(
        f"Done — {summary.get('total_rows', 0):,} total rows across "
        f"{len(summary.get('by_dataset', {}))} datasets → pr_all_awards_master.csv"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
