"""
Ingest Follow the Money CSV exports.

Place exported CSV files into  data/raw/Follow the Money/

Expected files:
  funding_flows_sf133.csv
  EP_PR_PRBank_Wire_Ledger_ALL.csv
  EP_PR_PRBank_Summary_ByEntity.csv
  EP_PR_PRBank_Summary_ByAccount.csv
  EP_PR_PRBank_Summary_ByYear.csv
  Municipal_Blind_Score_CORE6.csv
  municipality_political_federal_bridge.csv
  facility_matches_cross_exam.csv

Outputs (all in data/staging/processed/):
  pr_sf133_budget_execution.csv   — SF-133 federal budget execution by account
  pr_ftm_wire_ledger.csv          — PR bank wire transactions (ledger + summaries)
  pr_ftm_municipal_bridge.csv     — Municipal blind scores merged with political/federal bridge
  pr_ftm_facility_matches.csv     — Facility contract match cross-exam (pass-through)

Usage:
  python3 scripts/ingest_follow_the_money.py
  python3 scripts/ingest_follow_the_money.py --force
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from scripts.config import PROJECT_ROOT, setup_logging

RAW_DIR = PROJECT_ROOT / "data" / "raw" / "Follow the Money"

# ---------------------------------------------------------------------------
# Output column schemas
# ---------------------------------------------------------------------------

SF133_OUTPUT_COLUMNS = [
    "fiscal_year",
    "agency_code",
    "agency_name",
    "account_number",
    "account_title",
    "budget_authority",
    "obligations",
    "outlays",
    "unobligated_balance",
    "obligation_rate",
]

WIRE_COLUMNS = [
    "source_file",
    "txn_date",
    "entity_raw",
    "destination_bank",
    "destination_account",
    "amount_usd",
    "year",
]

MUNI_BRIDGE_COLUMNS = [
    "municipality",
    "blind_score",
    "node_count",
    "domain_diversity",
    "total_donated",
    "num_donors",
    "federal_rows",
    "federal_amount",
    "federal_unique_targets",
    "political_nodes",
    "political_federal_ratio",
]

FACILITY_COLUMNS = [
    "facility_cluster",
    "matched_contracts",
    "matched_obligation",
    "top_vendors",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _to_numeric(series: pd.Series) -> pd.Series:
    """Convert a series of strings to numeric, coercing errors to NaN."""
    return pd.to_numeric(
        series.astype(str).str.replace(r"[$,\s]", "", regex=True),
        errors="coerce",
    )


def _normalize_muni(name: str) -> str:
    """Lowercase, strip, collapse whitespace for municipality name matching."""
    if not name or pd.isna(name):
        return ""
    return " ".join(str(name).lower().strip().split())


# ---------------------------------------------------------------------------
# Output 1: SF-133 budget execution
# ---------------------------------------------------------------------------

def _build_sf133(df: pd.DataFrame, logger) -> pd.DataFrame:
    """
    Pivot SF-133 raw rows into one row per (fiscal_year, agency, account) with
    budget_authority and obligations separated by the is_obligation flag.
    """
    # Normalise the is_obligation column — accepts True/False/"True"/"False"/"1"/"0"/1/0
    df = df.copy()
    df["_is_obligation"] = (
        df["is_obligation"]
        .astype(str)
        .str.strip()
        .str.lower()
        .isin(["true", "1", "yes"])
    )

    # total_annual is the authoritative amount column
    df["_amount"] = _to_numeric(df["total_annual"])

    group_keys = ["report_year", "agency", "account", "omb_account"]

    oblig_df = (
        df[df["_is_obligation"]]
        .groupby(group_keys, dropna=False)["_amount"]
        .sum()
        .reset_index()
        .rename(columns={"_amount": "obligations"})
    )

    ba_df = (
        df[~df["_is_obligation"]]
        .groupby(group_keys, dropna=False)["_amount"]
        .sum()
        .reset_index()
        .rename(columns={"_amount": "budget_authority"})
    )

    merged = pd.merge(ba_df, oblig_df, on=group_keys, how="outer")

    merged["fiscal_year"]         = merged["report_year"].astype(str)
    merged["agency_code"]         = ""
    merged["agency_name"]         = merged["agency"].astype(str)
    merged["account_number"]      = merged["omb_account"].astype(str)
    merged["account_title"]       = merged["account"].astype(str)
    merged["budget_authority"]    = merged["budget_authority"].fillna(0)
    merged["obligations"]         = merged["obligations"].fillna(0)
    merged["outlays"]             = ""
    merged["unobligated_balance"] = ""

    ba = merged["budget_authority"]
    ob = merged["obligations"]
    merged["obligation_rate"] = (ob / ba.where(ba > 0)).round(4).astype(str)
    merged.loc[merged["obligation_rate"] == "nan", "obligation_rate"] = ""

    merged["budget_authority"] = merged["budget_authority"].astype(str)
    merged["obligations"]      = merged["obligations"].astype(str)

    logger.info(f"    SF-133: {len(merged):,} aggregated rows")
    return merged[SF133_OUTPUT_COLUMNS]


# ---------------------------------------------------------------------------
# Output 2: PR bank wire ledger
# ---------------------------------------------------------------------------

def _build_wire_ledger(
    ledger_df: pd.DataFrame,
    entity_df: pd.DataFrame,
    account_df: pd.DataFrame,
    year_df: pd.DataFrame,
    logger,
) -> pd.DataFrame:
    """
    Combine wire ledger detail with summary frames into WIRE_COLUMNS schema.
    Missing columns are filled with empty strings.
    """
    frames = []

    # --- detailed ledger ---
    if ledger_df is not None and not ledger_df.empty:
        ld = ledger_df.copy()
        row = pd.DataFrame(
            {
                "source_file":        ld.get("file", "EP_PR_PRBank_Wire_Ledger_ALL"),
                "txn_date":           ld.get("txn_date", ""),
                "entity_raw":         ld.get("entity_raw", ""),
                "destination_bank":   ld.get("destination_bank", ""),
                "destination_account": ld.get("destination_account", ""),
                "amount_usd":         ld.get("amount_usd", ""),
                "year":               "",
            }
        )
        frames.append(row)
        logger.info(f"    Wire ledger detail: {len(row):,} rows")

    # --- by-entity summary ---
    if entity_df is not None and not entity_df.empty:
        ed = entity_df.copy()
        row = pd.DataFrame(
            {
                "source_file":        "EP_PR_PRBank_Summary_ByEntity",
                "txn_date":           "",
                "entity_raw":         ed.get("entity_clean", ""),
                "destination_bank":   ed.get("destination_bank", ""),
                "destination_account": "",
                "amount_usd":         ed.get("amount_usd", ""),
                "year":               "",
            }
        )
        frames.append(row)
        logger.info(f"    Wire by-entity summary: {len(row):,} rows")

    # --- by-account summary ---
    if account_df is not None and not account_df.empty:
        ad = account_df.copy()
        row = pd.DataFrame(
            {
                "source_file":        "EP_PR_PRBank_Summary_ByAccount",
                "txn_date":           "",
                "entity_raw":         "",
                "destination_bank":   ad.get("destination_bank", ""),
                "destination_account": ad.get("destination_account", ""),
                "amount_usd":         ad.get("amount_usd", ""),
                "year":               "",
            }
        )
        frames.append(row)
        logger.info(f"    Wire by-account summary: {len(row):,} rows")

    # --- by-year summary ---
    if year_df is not None and not year_df.empty:
        yd = year_df.copy()
        row = pd.DataFrame(
            {
                "source_file":        "EP_PR_PRBank_Summary_ByYear",
                "txn_date":           "",
                "entity_raw":         "",
                "destination_bank":   yd.get("destination_bank", ""),
                "destination_account": "",
                "amount_usd":         yd.get("amount_usd", ""),
                "year":               yd.get("year", ""),
            }
        )
        frames.append(row)
        logger.info(f"    Wire by-year summary: {len(row):,} rows")

    if not frames:
        return pd.DataFrame(columns=WIRE_COLUMNS)

    combined = pd.concat(frames, ignore_index=True)
    for col in WIRE_COLUMNS:
        if col not in combined.columns:
            combined[col] = ""
    return combined[WIRE_COLUMNS].fillna("").astype(str)


# ---------------------------------------------------------------------------
# Output 3: Municipal bridge
# ---------------------------------------------------------------------------

def _build_muni_bridge(
    blind_df: pd.DataFrame,
    bridge_df: pd.DataFrame,
    logger,
) -> pd.DataFrame:
    """
    Join Municipal_Blind_Score with municipality_political_federal_bridge on
    normalised municipality name.
    """
    if blind_df is None and bridge_df is None:
        return pd.DataFrame(columns=MUNI_BRIDGE_COLUMNS)

    if blind_df is not None and not blind_df.empty:
        blind = blind_df.copy()
        blind["_muni_key"] = blind["Municipality"].apply(_normalize_muni)
        blind = blind.rename(
            columns={
                "Municipality":      "_muni_raw_blind",
                "Node_Count":        "node_count",
                "Domain_Diversity":  "domain_diversity",
                "Blind_Score_0_100": "blind_score",
            }
        )
    else:
        blind = pd.DataFrame()

    if bridge_df is not None and not bridge_df.empty:
        bridge = bridge_df.copy()
        # prefer muni_norm if present, else normalise municipality
        if "muni_norm" in bridge.columns:
            bridge["_muni_key"] = bridge["muni_norm"].apply(_normalize_muni)
        else:
            bridge["_muni_key"] = bridge["municipality"].apply(_normalize_muni)
        bridge = bridge.rename(
            columns={
                "municipality":            "_muni_raw_bridge",
                "city_norm":               "_city_norm",
                "total_donated":           "total_donated",
                "num_donors":              "num_donors",
                "federal_rows":            "federal_rows",
                "federal_amount":          "federal_amount",
                "federal_unique_targets":  "federal_unique_targets",
                "political_nodes":         "political_nodes",
                "political_federal_ratio": "political_federal_ratio",
            }
        )
    else:
        bridge = pd.DataFrame()

    if blind.empty and bridge.empty:
        return pd.DataFrame(columns=MUNI_BRIDGE_COLUMNS)

    if blind.empty:
        merged = bridge.copy()
        merged["municipality"] = merged.get("_muni_raw_bridge", merged["_muni_key"])
        for col in ["blind_score", "node_count", "domain_diversity"]:
            merged[col] = ""
    elif bridge.empty:
        merged = blind.copy()
        merged["municipality"] = merged["_muni_raw_blind"]
        for col in [
            "total_donated", "num_donors", "federal_rows", "federal_amount",
            "federal_unique_targets", "political_nodes", "political_federal_ratio",
        ]:
            merged[col] = ""
    else:
        merged = pd.merge(blind, bridge, on="_muni_key", how="outer")
        # Use blind name where available, else bridge name
        blind_name  = merged.get("_muni_raw_blind",  pd.Series([""] * len(merged)))
        bridge_name = merged.get("_muni_raw_bridge", pd.Series([""] * len(merged)))
        merged["municipality"] = blind_name.fillna("").where(
            blind_name.fillna("") != "", bridge_name.fillna("")
        )

    for col in MUNI_BRIDGE_COLUMNS:
        if col not in merged.columns:
            merged[col] = ""

    result = merged[MUNI_BRIDGE_COLUMNS].fillna("").astype(str)
    logger.info(f"    Municipal bridge: {len(result):,} rows")
    return result


# ---------------------------------------------------------------------------
# Output 4: Facility matches (pass-through)
# ---------------------------------------------------------------------------

def _build_facility(df: pd.DataFrame, logger) -> pd.DataFrame:
    """Rename raw columns to FACILITY_COLUMNS schema and pass through."""
    col_map = {
        "Facility Cluster":    "facility_cluster",
        "Matched Contracts":   "matched_contracts",
        "Matched Obligation":  "matched_obligation",
        "Top Vendors":         "top_vendors",
    }
    out = df.rename(columns=col_map)
    for col in FACILITY_COLUMNS:
        if col not in out.columns:
            out[col] = ""
    result = out[FACILITY_COLUMNS].fillna("").astype(str)
    logger.info(f"    Facility matches: {len(result):,} rows")
    return result


# ---------------------------------------------------------------------------
# Main run()
# ---------------------------------------------------------------------------

def run(root: Path = None, force: bool = False) -> dict:
    if root is None:
        root = PROJECT_ROOT
    root = Path(root)
    raw_dir = root / "data" / "raw" / "Follow the Money"
    out_dir = root / "data" / "staging" / "processed"
    out_dir.mkdir(parents=True, exist_ok=True)

    primary_out = out_dir / "pr_sf133_budget_execution.csv"

    logger = setup_logging("ingest_follow_the_money")

    # Cache check on primary output
    if not force and primary_out.exists():
        try:
            existing = pd.read_csv(primary_out, dtype=str, low_memory=False)
            if len(existing) > 0:
                logger.info(f"  Cached — {len(existing):,} rows in {primary_out.name}")
                return {"rows": len(existing), "path": str(primary_out), "status": "CACHED"}
        except Exception:
            pass

    if not raw_dir.exists():
        logger.info(f"  No Follow the Money raw dir at {raw_dir} — skipping ingest")
        return {"rows": 0, "path": str(primary_out), "status": "NO_FILES"}

    # ------------------------------------------------------------------
    # Read all source files (each is optional; warn if missing)
    # ------------------------------------------------------------------

    def _read(filename: str) -> pd.DataFrame | None:
        path = raw_dir / filename
        if not path.exists():
            logger.warning(f"  Missing expected file: {filename}")
            return None
        try:
            df = pd.read_csv(path, dtype=str, low_memory=False)
            logger.info(f"  Read {filename}: {len(df):,} rows")
            return df
        except Exception as exc:
            logger.warning(f"  Could not read {filename}: {exc}")
            return None

    sf133_df      = _read("funding_flows_sf133.csv")
    ledger_df     = _read("EP_PR_PRBank_Wire_Ledger_ALL.csv")
    entity_df     = _read("EP_PR_PRBank_Summary_ByEntity.csv")
    account_df    = _read("EP_PR_PRBank_Summary_ByAccount.csv")
    year_df       = _read("EP_PR_PRBank_Summary_ByYear.csv")
    blind_df      = _read("Municipal_Blind_Score_CORE6.csv")
    bridge_df     = _read("municipality_political_federal_bridge.csv")
    facility_df   = _read("facility_matches_cross_exam.csv")

    all_missing = all(
        df is None
        for df in [sf133_df, ledger_df, entity_df, account_df,
                   year_df, blind_df, bridge_df, facility_df]
    )
    if all_missing:
        logger.warning("  No readable Follow the Money files found")
        return {"rows": 0, "path": str(primary_out), "status": "NO_FILES"}

    # ------------------------------------------------------------------
    # Output 1: SF-133 budget execution
    # ------------------------------------------------------------------
    sf133_rows = 0
    if sf133_df is not None and not sf133_df.empty:
        try:
            sf133_out = _build_sf133(sf133_df, logger)
            sf133_out.to_csv(primary_out, index=False, encoding="utf-8")
            sf133_rows = len(sf133_out)
            logger.info(f"  Written: {primary_out.name} ({sf133_rows:,} rows)")
        except Exception as exc:
            logger.warning(f"  SF-133 build failed: {exc}")
    else:
        logger.info("  No SF-133 data — writing empty schema")
        pd.DataFrame(columns=SF133_OUTPUT_COLUMNS).to_csv(
            primary_out, index=False, encoding="utf-8"
        )

    # ------------------------------------------------------------------
    # Output 2: Wire ledger
    # ------------------------------------------------------------------
    wire_out_path = out_dir / "pr_ftm_wire_ledger.csv"
    try:
        wire_df = _build_wire_ledger(ledger_df, entity_df, account_df, year_df, logger)
        wire_df.to_csv(wire_out_path, index=False, encoding="utf-8")
        logger.info(f"  Written: {wire_out_path.name} ({len(wire_df):,} rows)")
    except Exception as exc:
        logger.warning(f"  Wire ledger build failed: {exc}")

    # ------------------------------------------------------------------
    # Output 3: Municipal bridge
    # ------------------------------------------------------------------
    muni_out_path = out_dir / "pr_ftm_municipal_bridge.csv"
    try:
        muni_df = _build_muni_bridge(blind_df, bridge_df, logger)
        muni_df.to_csv(muni_out_path, index=False, encoding="utf-8")
        logger.info(f"  Written: {muni_out_path.name} ({len(muni_df):,} rows)")
    except Exception as exc:
        logger.warning(f"  Municipal bridge build failed: {exc}")

    # ------------------------------------------------------------------
    # Output 4: Facility matches
    # ------------------------------------------------------------------
    facility_out_path = out_dir / "pr_ftm_facility_matches.csv"
    if facility_df is not None and not facility_df.empty:
        try:
            fac_df = _build_facility(facility_df, logger)
            fac_df.to_csv(facility_out_path, index=False, encoding="utf-8")
            logger.info(f"  Written: {facility_out_path.name} ({len(fac_df):,} rows)")
        except Exception as exc:
            logger.warning(f"  Facility matches build failed: {exc}")
    else:
        pd.DataFrame(columns=FACILITY_COLUMNS).to_csv(
            facility_out_path, index=False, encoding="utf-8"
        )

    status = "OK" if sf133_rows > 0 else "EMPTY"
    return {"rows": sf133_rows, "path": str(primary_out), "status": status}


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Ingest Follow the Money CSV exports from data/raw/Follow the Money/"
    )
    parser.add_argument(
        "--force", action="store_true", help="Re-ingest even if output exists"
    )
    args = parser.parse_args()
    result = run(force=args.force)
    print(f"\nFollow the Money ingest: {result['rows']:,} rows — {result['status']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
