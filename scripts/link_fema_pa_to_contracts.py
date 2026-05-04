"""
Link FEMA PA project worksheets to COR3 recovery projects, contracts, and entity master.

Inputs:
  data/normalized/fema_pa_projects_v2.parquet
  data/normalized/fema_pa_portal_178_pws.parquet
  data/staging/processed/pr_cor3_projects.csv
  data/staging/processed/pr_contracts_master.csv   (or pr_all_awards_master.csv)
  data/staging/processed/entity_master.csv

Outputs:
  data/linked/fema_178_pw_linkage.csv
  data/review/fema_pa_unmatched_178_pws.csv

Usage:
  python3 scripts/link_fema_pa_to_contracts.py
  python3 scripts/link_fema_pa_to_contracts.py --force
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from scripts.build_unified_master import _normalize_name
from scripts.parquet_utils import pq_read, pq_write
from scripts.config import PROJECT_ROOT, setup_logging

NORMALIZED_DIR = PROJECT_ROOT / "data" / "normalized"
LINKED_DIR     = PROJECT_ROOT / "data" / "linked"
REVIEW_DIR     = PROJECT_ROOT / "data" / "review"
PROCESSED_DIR  = PROJECT_ROOT / "data" / "staging" / "processed"

LINKAGE_COLUMNS = [
    "pw_number", "disaster_number",
    "applicant_name", "applicant_normalized",
    "v2_project_amount", "v2_federal_share_obligated",
    "portal_eligible_amount", "portal_federal_share",
    "cor3_project_id", "cor3_total_approved", "cor3_disbursement_rate",
    "contract_id", "recipient_name",
    "link_confidence",
    "matched_cor3", "matched_contract", "matched_entity",
    "county", "municipality", "category",
]

UNMATCHED_COLUMNS = [
    "pw_number", "disaster_number", "applicant_name",
    "eligible_amount", "federal_share", "category", "status", "source_file",
]


def _load_parquet(path, logger, columns=None):
    if not path.exists():
        logger.warning(f"  Missing: {path.name}")
        return pd.DataFrame(columns=columns or [])
    try:
        df = pq_read(path)
        logger.info(f"  Loaded {len(df):,} rows from {path.name}")
        return df
    except Exception as e:
        logger.warning(f"  Failed to read {path.name}: {e}")
        return pd.DataFrame(columns=columns or [])


def _load_csv(path, logger):
    if not path.exists():
        logger.warning(f"  Missing: {path.name}")
        return pd.DataFrame()
    try:
        df = pd.read_csv(path, dtype=str, low_memory=False)
        logger.info(f"  Loaded {len(df):,} rows from {path.name}")
        return df
    except Exception as e:
        logger.warning(f"  Failed to read {path.name}: {e}")
        return pd.DataFrame()


def _norm(s):
    if pd.isna(s) or not str(s).strip():
        return ""
    return _normalize_name(str(s))


def _build_linkage(df_v2, df_portal, df_cor3, df_contracts, df_entity, logger):
    rows = []

    # Build lookup tables
    cor3_lookup = {}
    if not df_cor3.empty and "applicant_normalized" in df_cor3.columns:
        for _, r in df_cor3.iterrows():
            key = str(r.get("applicant_normalized", "")).strip()
            if key:
                cor3_lookup[key] = r

    contract_lookup = {}
    name_col = None
    for col in ["recipient_name_normalized", "recipient_name"]:
        if not df_contracts.empty and col in df_contracts.columns:
            name_col = col
            break
    if name_col and not df_contracts.empty:
        for _, r in df_contracts.iterrows():
            key = _norm(r.get(name_col, ""))
            if key and key not in contract_lookup:
                contract_lookup[key] = r

    entity_lookup = {}
    if not df_entity.empty:
        for col in ["canonical_name_normalized", "norm_key"]:
            if col in df_entity.columns:
                for _, r in df_entity.iterrows():
                    key = str(r.get(col, "")).strip()
                    if key:
                        entity_lookup[key] = r
                break

    # Build portal lookup by pw_number + disaster_number
    portal_lookup = {}
    if not df_portal.empty:
        for _, r in df_portal.iterrows():
            pw = str(r.get("pw_number", "")).strip()
            dis = str(r.get("disaster_number", "")).strip()
            key = (pw, dis)
            if pw:
                portal_lookup[key] = r

    # Source: v2 projects
    if not df_v2.empty:
        for _, r in df_v2.iterrows():
            pw = str(r.get("pw_number", "")).strip()
            dis = str(r.get("disaster_number", "")).strip()
            applicant = str(r.get("applicant_name", "")).strip()
            norm_key = _norm(applicant)

            portal_row = portal_lookup.get((pw, dis), {})
            cor3_row = cor3_lookup.get(norm_key, {})
            contract_row = contract_lookup.get(norm_key, {})
            entity_row = entity_lookup.get(norm_key, {})

            matched_cor3 = bool(cor3_row)
            matched_contract = bool(contract_row)
            matched_entity = bool(entity_row)

            if matched_contract or matched_entity:
                link_confidence = "exact"
            elif matched_cor3:
                link_confidence = "partial"
            else:
                link_confidence = "none"

            rows.append({
                "pw_number":               pw,
                "disaster_number":         dis,
                "applicant_name":          applicant,
                "applicant_normalized":    norm_key,
                "v2_project_amount":       r.get("project_amount", 0),
                "v2_federal_share_obligated": r.get("federal_share_obligated", 0),
                "portal_eligible_amount":  portal_row.get("eligible_amount", "") if portal_row else "",
                "portal_federal_share":    portal_row.get("federal_share", "") if portal_row else "",
                "cor3_project_id":         str(cor3_row.get("project_id", "")) if cor3_row else "",
                "cor3_total_approved":     cor3_row.get("total_approved", "") if cor3_row else "",
                "cor3_disbursement_rate":  cor3_row.get("disbursement_rate", "") if cor3_row else "",
                "contract_id":             str(contract_row.get("award_id", "")) if contract_row else "",
                "recipient_name":          str(contract_row.get("recipient_name", "")) if contract_row else "",
                "link_confidence":         link_confidence,
                "matched_cor3":            matched_cor3,
                "matched_contract":        matched_contract,
                "matched_entity":          matched_entity,
                "county":                  r.get("county", ""),
                "municipality":            r.get("county", ""),
                "category":                r.get("category", ""),
            })

    df_out = pd.DataFrame(rows, columns=LINKAGE_COLUMNS) if rows else pd.DataFrame(columns=LINKAGE_COLUMNS)
    logger.info(f"  Linkage: {len(df_out):,} rows")
    return df_out


def run(root=None, force=False):
    root = Path(root or PROJECT_ROOT)
    linked_path   = root / "data" / "linked" / "fema_178_pw_linkage.csv"
    unmatched_path = root / "data" / "review" / "fema_pa_unmatched_178_pws.csv"
    logger = setup_logging("link_fema_pa_to_contracts")

    LINKED_DIR.mkdir(parents=True, exist_ok=True)
    REVIEW_DIR.mkdir(parents=True, exist_ok=True)

    if linked_path.exists() and not force:
        rows = len(pd.read_csv(linked_path, dtype=str, nrows=10000))
        logger.info(f"  fema_178_pw_linkage.csv exists ({rows:,} rows) — skipping.")
        return {"linkage_rows": rows, "unmatched_pws": 0, "matched_pct": 0.0, "status": "CACHED"}

    logger.info("Loading inputs...")
    df_v2     = _load_parquet(root / "data" / "normalized" / "fema_pa_projects_v2.parquet", logger)
    df_portal = _load_parquet(root / "data" / "normalized" / "fema_pa_portal_178_pws.parquet", logger)
    df_cor3   = _load_csv(root / "data" / "staging" / "processed" / "pr_cor3_projects.csv", logger)
    df_contracts = _load_csv(root / "data" / "staging" / "processed" / "pr_contracts_master.csv", logger)
    if df_contracts.empty:
        df_contracts = _load_csv(root / "data" / "staging" / "processed" / "pr_all_awards_master.csv", logger)
    df_entity = _load_csv(root / "data" / "staging" / "processed" / "entity_master.csv", logger)

    df_linkage = _build_linkage(df_v2, df_portal, df_cor3, df_contracts, df_entity, logger)
    df_linkage.to_csv(linked_path, index=False, encoding="utf-8")

    # Unmatched portal PWs
    if not df_portal.empty:
        matched_pws = set(
            df_linkage[df_linkage["pw_number"] != ""]["pw_number"].astype(str)
        )
        portal_pws = set(df_portal.get("pw_number", pd.Series(dtype=str)).astype(str))
        unmatched_pws = portal_pws - matched_pws
        df_unmatched = df_portal[
            df_portal.get("pw_number", pd.Series(dtype=str)).astype(str).isin(unmatched_pws)
        ]
        for col in UNMATCHED_COLUMNS:
            if col not in df_unmatched.columns:
                df_unmatched = df_unmatched.copy()
                df_unmatched[col] = ""
        df_unmatched[UNMATCHED_COLUMNS].to_csv(unmatched_path, index=False, encoding="utf-8")
        unmatched_count = len(df_unmatched)
    else:
        pd.DataFrame(columns=UNMATCHED_COLUMNS).to_csv(unmatched_path, index=False)
        unmatched_count = 0

    total = len(df_linkage)
    matched = (df_linkage["link_confidence"] != "none").sum() if total else 0
    matched_pct = round(matched / total * 100, 1) if total else 0.0

    logger.info(f"  Linkage: {total:,} rows, {matched:,} matched ({matched_pct:.1f}%), {unmatched_count} unmatched portal PWs")
    return {"linkage_rows": total, "unmatched_pws": unmatched_count, "matched_pct": matched_pct, "status": "OK"}


def main():
    parser = argparse.ArgumentParser(description="Link FEMA PA PWs to contracts/entities")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    result = run(force=args.force)
    print(f"\nFEMA PA linkage: {result['linkage_rows']:,} rows, {result['matched_pct']:.1f}% matched")
    return 0


if __name__ == "__main__":
    sys.exit(main())
