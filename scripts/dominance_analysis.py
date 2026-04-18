"""
Dominance Analysis — Market Concentration & Vendor Rankings

Computes:
  1. Top 25 vendors by total obligation (raw + parent-entity consolidated)
  2. HHI (Herfindahl-Hirschman Index) per agency — market concentration
  3. Year-over-year vendor share trends (top 10)
  4. Single-source vs multi-agency vendor ratio
  5. Geographic concentration by pop_state

Usage:
  python3 scripts/dominance_analysis.py
  python3 scripts/dominance_analysis.py --top 50   # top 50 vendors in report
"""

import argparse
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from scripts.config import MASTER_PATH, PROCESSED_DIR, PROJECT_ROOT, setup_logging

TOP_N_DEFAULT = 25


def load_master(root: Path) -> pd.DataFrame:
    """Load enriched master (preferred) or plain master."""
    enriched = root / "data" / "staging" / "processed" / "enrichment" / "master_enriched.csv"
    plain = root / "data" / "staging" / "processed" / "pr_contracts_master.csv"
    path = enriched if enriched.exists() else plain
    if not path.exists():
        raise FileNotFoundError(f"No master CSV at {path}")
    df = pd.read_csv(path, dtype=str, low_memory=False)
    df["obligated_amount"] = pd.to_numeric(df.get("obligated_amount"), errors="coerce").fillna(0)
    df["fiscal_year"] = pd.to_numeric(df.get("fiscal_year"), errors="coerce")
    df["vendor_name"] = df.get("vendor_name", pd.Series(dtype=str)).fillna("").str.strip()
    df["agency_name"] = df.get("agency_name", pd.Series(dtype=str)).fillna("UNKNOWN").str.strip()
    return df


def load_hierarchy(root: Path) -> pd.DataFrame | None:
    """Load entity_hierarchy.csv if it exists."""
    path = root / "data" / "staging" / "processed" / "enrichment" / "entity_hierarchy.csv"
    if not path.exists():
        return None
    df = pd.read_csv(path, dtype=str, low_memory=False)
    df["total_obligation"] = pd.to_numeric(df.get("total_obligation"), errors="coerce").fillna(0)
    return df


def apply_parent_consolidation(df: pd.DataFrame, hierarchy: pd.DataFrame) -> pd.DataFrame:
    """Replace vendor_name with parent_name where available."""
    parent_map = {}
    for _, row in hierarchy.iterrows():
        vn = (row.get("vendor_name") or "").strip()
        pn = (row.get("parent_name") or "").strip()
        if vn and pn:
            parent_map[vn] = pn
    df = df.copy()
    df["entity_name"] = df["vendor_name"].map(parent_map).fillna(df["vendor_name"])
    return df


def compute_top_vendors(df: pd.DataFrame, top_n: int, col: str = "vendor_name") -> pd.DataFrame:
    grp = df.groupby(col).agg(
        total_obligation=("obligated_amount", "sum"),
        record_count=("obligated_amount", "count"),
        agencies_served=("agency_name", "nunique"),
        fy_min=("fiscal_year", "min"),
        fy_max=("fiscal_year", "max"),
    ).reset_index()
    grp = grp.rename(columns={col: "vendor_name"})
    total = grp["total_obligation"].sum()
    grp["market_share_pct"] = (grp["total_obligation"] / total * 100).round(2)
    grp = grp.sort_values("total_obligation", ascending=False).head(top_n)
    grp["rank"] = range(1, len(grp) + 1)
    return grp


def compute_hhi_per_agency(df: pd.DataFrame) -> pd.DataFrame:
    """Compute HHI for each agency. HHI = sum of squared market shares."""
    results = []
    for agency, grp in df.groupby("agency_name"):
        total = grp["obligated_amount"].sum()
        if total <= 0:
            continue
        shares = grp.groupby("vendor_name")["obligated_amount"].sum() / total * 100
        hhi = (shares ** 2).sum()
        top_vendor = shares.idxmax()
        top_share = shares.max()
        results.append({
            "agency_name": agency,
            "hhi": round(hhi, 1),
            "concentration": "HIGH" if hhi > 2500 else ("MODERATE" if hhi > 1500 else "LOW"),
            "total_obligation": round(total, 2),
            "vendor_count": len(shares),
            "top_vendor": top_vendor,
            "top_vendor_share_pct": round(top_share, 2),
        })
    return pd.DataFrame(results).sort_values("hhi", ascending=False)


def compute_yoy_trends(df: pd.DataFrame, top_n: int = 10) -> pd.DataFrame:
    """Year-over-year obligation trends for top vendors."""
    top_vendors = (
        df.groupby("vendor_name")["obligated_amount"].sum()
        .nlargest(top_n).index.tolist()
    )
    filtered = df[df["vendor_name"].isin(top_vendors)]
    pivot = filtered.groupby(["fiscal_year", "vendor_name"])["obligated_amount"].sum().unstack(fill_value=0)
    pivot = pivot.reset_index()
    return pivot


def compute_single_source(df: pd.DataFrame) -> pd.DataFrame:
    """Identify vendors that appear in only 1 vs multiple agencies."""
    grp = df.groupby("vendor_name")["agency_name"].nunique().reset_index()
    grp.columns = ["vendor_name", "agency_count"]
    grp["category"] = grp["agency_count"].apply(
        lambda n: "single_agency" if n == 1 else ("few_agencies" if n <= 3 else "multi_agency")
    )
    return grp.sort_values("agency_count", ascending=False)


def compute_geo_concentration(df: pd.DataFrame) -> pd.DataFrame:
    """Obligation by place of performance state."""
    if "pop_state" not in df.columns:
        return pd.DataFrame()
    grp = df.groupby("pop_state").agg(
        total_obligation=("obligated_amount", "sum"),
        record_count=("obligated_amount", "count"),
    ).reset_index()
    total = grp["total_obligation"].sum()
    grp["share_pct"] = (grp["total_obligation"] / total * 100).round(2)
    return grp.sort_values("total_obligation", ascending=False)


def run(root: Path = None, top_n: int = TOP_N_DEFAULT) -> dict:
    if root is None:
        root = PROJECT_ROOT

    output_dir = root / "data" / "staging" / "processed"
    output_dir.mkdir(parents=True, exist_ok=True)

    logger = setup_logging("dominance_analysis")
    logger.info(f"Dominance analysis — top {top_n} vendors")

    df = load_master(root)
    hierarchy = load_hierarchy(root)
    logger.info(f"  Loaded {len(df):,} rows, {df['vendor_name'].nunique():,} unique vendors")

    outputs = {}

    # 1. Top vendors (raw)
    top_raw = compute_top_vendors(df, top_n)
    out_raw = output_dir / "dominance_top_vendors_raw.csv"
    top_raw.to_csv(out_raw, index=False)
    logger.info(f"  Top {top_n} vendors (raw): {out_raw.name}")
    outputs["top_vendors_raw"] = str(out_raw)

    # 2. Top vendors (parent-consolidated)
    if hierarchy is not None:
        df_parent = apply_parent_consolidation(df, hierarchy)
        top_parent = compute_top_vendors(df_parent, top_n, col="entity_name")
        out_parent = output_dir / "dominance_top_vendors_consolidated.csv"
        top_parent.to_csv(out_parent, index=False)
        logger.info(f"  Top {top_n} vendors (consolidated): {out_parent.name}")
        outputs["top_vendors_consolidated"] = str(out_parent)
    else:
        logger.info("  No entity hierarchy found — skipping consolidated ranking")

    # 3. HHI per agency
    hhi = compute_hhi_per_agency(df)
    out_hhi = output_dir / "dominance_hhi_per_agency.csv"
    hhi.to_csv(out_hhi, index=False)
    high_hhi = hhi[hhi["concentration"] == "HIGH"]
    logger.info(f"  HHI per agency: {len(hhi)} agencies, {len(high_hhi)} HIGH concentration")
    outputs["hhi_per_agency"] = str(out_hhi)

    # 4. Year-over-year trends
    yoy = compute_yoy_trends(df)
    out_yoy = output_dir / "dominance_yoy_trends.csv"
    yoy.to_csv(out_yoy, index=False)
    logger.info(f"  YoY trends: {out_yoy.name}")
    outputs["yoy_trends"] = str(out_yoy)

    # 5. Single-source analysis
    ss = compute_single_source(df)
    out_ss = output_dir / "dominance_single_source.csv"
    ss.to_csv(out_ss, index=False)
    single = (ss["category"] == "single_agency").sum()
    logger.info(f"  Single-agency vendors: {single}/{len(ss)} ({single/max(len(ss),1)*100:.1f}%)")
    outputs["single_source"] = str(out_ss)

    # 6. Geographic concentration
    geo = compute_geo_concentration(df)
    if not geo.empty:
        out_geo = output_dir / "dominance_geo_concentration.csv"
        geo.to_csv(out_geo, index=False)
        logger.info(f"  Geographic distribution: {out_geo.name}")
        outputs["geo_concentration"] = str(out_geo)

    # Summary JSON
    total_obligation = df["obligated_amount"].sum()
    top3_share = top_raw.head(3)["total_obligation"].sum() / max(total_obligation, 1) * 100
    summary = {
        "total_rows": len(df),
        "unique_vendors": int(df["vendor_name"].nunique()),
        "unique_agencies": int(df["agency_name"].nunique()),
        "total_obligation_usd": round(total_obligation, 2),
        "top3_vendor_share_pct": round(top3_share, 2),
        "top_vendor": top_raw.iloc[0]["vendor_name"] if len(top_raw) else "",
        "top_vendor_obligation": round(top_raw.iloc[0]["total_obligation"], 2) if len(top_raw) else 0,
        "high_hhi_agencies": int(len(high_hhi)),
        "fiscal_years": sorted(df["fiscal_year"].dropna().astype(int).unique().tolist()),
        "outputs": outputs,
    }
    summary_path = output_dir / "dominance_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    logger.info(f"\nDominance summary:")
    logger.info(f"  Total obligation:  ${total_obligation:>15,.0f}")
    logger.info(f"  Top 3 share:       {top3_share:.1f}%")
    logger.info(f"  Top vendor:        {summary['top_vendor']}")
    logger.info(f"  High-HHI agencies: {len(high_hhi)}")
    logger.info(f"  Summary → {summary_path.name}")

    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Dominance and market concentration analysis")
    parser.add_argument("--top", type=int, default=TOP_N_DEFAULT, help="Top N vendors to rank")
    args = parser.parse_args()
    run(top_n=args.top)
    return 0


if __name__ == "__main__":
    sys.exit(main())
