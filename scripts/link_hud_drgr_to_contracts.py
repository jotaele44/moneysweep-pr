"""
Link HUD DRGR responsible organizations to federal contracts and entity master.

Inputs:
  data/normalized/hud_drgr_responsible_orgs_resolved.parquet
  data/normalized/hud_drgr_activities.parquet
  data/staging/processed/pr_contracts_master.csv  (or pr_all_awards_master.csv)
  data/staging/processed/entity_master.csv

Output:
  data/linked/hud_drgr_financial_linkage.csv

Usage:
  python3 scripts/link_hud_drgr_to_contracts.py
  python3 scripts/link_hud_drgr_to_contracts.py --force
"""

import argparse
import sys
from difflib import SequenceMatcher
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from scripts.build_unified_master import _normalize_name
from scripts.parquet_utils import pq_read, pq_write
from scripts.config import PROJECT_ROOT, setup_logging

LINKED_DIR = PROJECT_ROOT / "data" / "linked"

LINKAGE_COLUMNS = [
    "responsible_org", "responsible_org_normalized",
    "matched_entity", "matched_entity_normalized",
    "link_confidence",
    "matched_contract_count", "matched_contract_total",
    "grant_number_list",
    "activity_count", "total_budget_managed",
]

FUZZY_THRESHOLD = 0.85


def _load_parquet(path, logger):
    if not path.exists():
        logger.warning(f"  Missing: {path.name}")
        return pd.DataFrame()
    try:
        df = pq_read(path)
        logger.info(f"  Loaded {len(df):,} rows from {path.name}")
        return df
    except Exception as e:
        logger.warning(f"  Failed to read {path.name}: {e}")
        return pd.DataFrame()


def _load_csv(path, logger):
    if not path.exists():
        return pd.DataFrame()
    try:
        df = pd.read_csv(path, dtype=str, low_memory=False)
        logger.info(f"  Loaded {len(df):,} rows from {path.name}")
        return df
    except Exception as e:
        logger.warning(f"  Failed to read {path.name}: {e}")
        return pd.DataFrame()


def _similarity(a, b):
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def _find_match(norm_key, exact_lookup, fuzzy_keys):
    """Return (matched_norm_key, confidence)."""
    if not norm_key:
        return "", "none"
    if norm_key in exact_lookup:
        return norm_key, "exact"
    best_score, best_key = 0.0, ""
    for candidate in fuzzy_keys:
        score = _similarity(norm_key, candidate)
        if score > best_score:
            best_score, best_key = score, candidate
    if best_score >= FUZZY_THRESHOLD:
        return best_key, "fuzzy"
    return "", "none"


def run(root=None, force=False):
    root = Path(root or PROJECT_ROOT)
    LINKED_DIR.mkdir(parents=True, exist_ok=True)
    out_path = root / "data" / "linked" / "hud_drgr_financial_linkage.csv"
    logger = setup_logging("link_hud_drgr_to_contracts")

    if out_path.exists() and not force:
        rows = len(pd.read_csv(out_path, dtype=str, nrows=10000))
        logger.info(f"  hud_drgr_financial_linkage.csv exists ({rows:,} rows) — skipping.")
        return {"linkage_rows": rows, "matched_pct": 0.0, "status": "CACHED"}

    norm_dir = root / "data" / "normalized"
    proc_dir = root / "data" / "staging" / "processed"

    df_orgs       = _load_parquet(norm_dir / "hud_drgr_responsible_orgs_resolved.parquet", logger)
    df_activities = _load_parquet(norm_dir / "hud_drgr_activities.parquet", logger)
    df_contracts  = _load_csv(proc_dir / "pr_contracts_master.csv", logger)
    if df_contracts.empty:
        df_contracts = _load_csv(proc_dir / "pr_all_awards_master.csv", logger)
    df_entity = _load_csv(proc_dir / "entity_master.csv", logger)

    if df_orgs.empty:
        logger.warning("  No responsible org data — writing empty linkage")
        pd.DataFrame(columns=LINKAGE_COLUMNS).to_csv(out_path, index=False)
        return {"linkage_rows": 0, "matched_pct": 0.0, "status": "EMPTY"}

    # Build contract lookup (normalized name → aggregate stats)
    contract_exact = {}
    name_col = None
    for col in ["recipient_name_normalized", "recipient_name"]:
        if not df_contracts.empty and col in df_contracts.columns:
            name_col = col
            break

    if name_col and not df_contracts.empty:
        for norm_key, grp in df_contracts.groupby(df_contracts[name_col].apply(_normalize_name)):
            if norm_key:
                amt = pd.to_numeric(grp.get("obligated_amount", pd.Series(dtype=float)), errors="coerce").fillna(0).sum()
                contract_exact[norm_key] = {
                    "recipient_name": grp[name_col].iloc[0],
                    "count": len(grp),
                    "total": amt,
                }

    # Build entity lookup
    entity_exact = {}
    if not df_entity.empty:
        for col in ["canonical_name_normalized", "norm_key"]:
            if col in df_entity.columns:
                for _, r in df_entity.iterrows():
                    key = str(r.get(col, "")).strip()
                    if key:
                        entity_exact[key] = r.get("canonical_name", r.get("entity_name", key))
                break

    all_norm_keys = set(contract_exact.keys()) | set(entity_exact.keys())
    fuzzy_keys = list(all_norm_keys)

    rows = []
    for _, org_row in df_orgs.iterrows():
        org = str(org_row.get("responsible_org", "")).strip()
        org_norm = str(org_row.get("responsible_org_normalized", _normalize_name(org))).strip()

        matched_key, confidence = _find_match(org_norm, all_norm_keys, fuzzy_keys)

        if matched_key in contract_exact:
            matched_entity = contract_exact[matched_key]["recipient_name"]
            count = contract_exact[matched_key]["count"]
            total = contract_exact[matched_key]["total"]
        elif matched_key in entity_exact:
            matched_entity = entity_exact[matched_key]
            count, total = 0, 0
        else:
            matched_entity, count, total = "", 0, 0

        rows.append({
            "responsible_org":           org,
            "responsible_org_normalized": org_norm,
            "matched_entity":            matched_entity,
            "matched_entity_normalized": matched_key,
            "link_confidence":           confidence,
            "matched_contract_count":    count,
            "matched_contract_total":    total,
            "grant_number_list":         org_row.get("grant_number_list", ""),
            "activity_count":            org_row.get("activity_count", 0),
            "total_budget_managed":      org_row.get("total_budget_managed", 0),
        })

    df_out = pd.DataFrame(rows, columns=LINKAGE_COLUMNS) if rows else pd.DataFrame(columns=LINKAGE_COLUMNS)
    df_out.to_csv(out_path, index=False, encoding="utf-8")

    total = len(df_out)
    matched = (df_out["link_confidence"] != "none").sum() if total else 0
    matched_pct = round(matched / total * 100, 1) if total else 0.0
    logger.info(f"  Linkage: {total:,} orgs, {matched:,} matched ({matched_pct:.1f}%)")

    return {"linkage_rows": total, "matched_pct": matched_pct, "status": "OK"}


def main():
    parser = argparse.ArgumentParser(description="Link HUD DRGR orgs to contracts/entities")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    result = run(force=args.force)
    print(f"\nHUD DRGR linkage: {result['linkage_rows']:,} rows, {result['matched_pct']:.1f}% matched")
    return 0


if __name__ == "__main__":
    sys.exit(main())
