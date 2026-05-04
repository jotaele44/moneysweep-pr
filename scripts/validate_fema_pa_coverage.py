"""
Validate FEMA PA coverage: 178-PW loading, v1 vs v2 diff, gap analysis, high-value unresolved.

Inputs:
  data/normalized/fema_pa_projects_v2.parquet
  data/normalized/fema_pa_portal_178_pws.parquet
  data/linked/fema_178_pw_linkage.csv

Outputs:
  data/validation/fema_pa_gap_report.csv
  data/validation/fema_pa_v1_v2_diff_report.csv
  data/review/fema_pa_high_value_unresolved.csv

Usage:
  python3 scripts/validate_fema_pa_coverage.py
  python3 scripts/validate_fema_pa_coverage.py --force
"""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import requests

from scripts.config import PROJECT_ROOT, setup_logging

NORMALIZED_DIR  = PROJECT_ROOT / "data" / "normalized"
VALIDATION_DIR  = PROJECT_ROOT / "data" / "validation"
REVIEW_DIR      = PROJECT_ROOT / "data" / "review"
LINKED_DIR      = PROJECT_ROOT / "data" / "linked"

PW_TARGET = 178
HIGH_VALUE_THRESHOLD = 1_000_000

FEMA_V1_PA = "https://www.fema.gov/api/open/v1/PublicAssistanceFundedProjectsDetails"
FEMA_V2_PA = "https://www.fema.gov/api/open/v2/PublicAssistanceFundedProjectsDetails"
PAGE_SIZE = 1000

GAP_COLUMNS = [
    "pw_number", "disaster_number", "applicant_name", "category",
    "project_amount", "gap_reason",
]
DIFF_COLUMNS = [
    "metric", "v1_value", "v2_value", "difference", "pct_difference",
]
HIGH_VALUE_COLUMNS = [
    "pw_number", "disaster_number", "applicant_name",
    "project_amount", "link_confidence", "review_note",
]


def _load_parquet(path, logger):
    if not path.exists():
        logger.warning(f"  Missing: {path.name}")
        return pd.DataFrame()
    try:
        df = pd.read_parquet(path, engine="pyarrow")
        logger.info(f"  Loaded {len(df):,} rows from {path.name}")
        return df
    except Exception as e:
        logger.warning(f"  Failed to read {path.name}: {e}")
        return pd.DataFrame()


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


def _fetch_count_and_amount(endpoint, logger):
    """Fetch first page from a PA endpoint, return (count, total_amount)."""
    try:
        url = f"{endpoint}?$top={PAGE_SIZE}&$skip=0&$filter=state eq 'PR'"
        resp = requests.get(url, timeout=30)
        if resp.status_code != 200:
            logger.warning(f"  {endpoint} returned HTTP {resp.status_code}")
            return None, None
        data = resp.json()
        meta = data.get("metadata", {})
        count = meta.get("count", None)
        records = data.get(endpoint.split("/")[-1], [])
        total = sum(
            float(r.get("projectAmount", 0) or 0) for r in records
        )
        return count, total
    except Exception as e:
        logger.warning(f"  V1/V2 diff fetch failed: {e}")
        return None, None


def _build_v1_v2_diff(df_v2, logger):
    """Fetch v1 summary and compare to v2 loaded data."""
    rows = []

    v2_count = len(df_v2) if not df_v2.empty else 0
    v2_amount = pd.to_numeric(df_v2.get("project_amount", pd.Series(dtype=float)), errors="coerce").sum() if not df_v2.empty else 0

    logger.info("  Fetching v1 sample for diff comparison...")
    v1_count_raw, v1_amount_sample = _fetch_count_and_amount(FEMA_V1_PA, logger)
    time.sleep(1)

    def _diff_row(metric, v1, v2):
        v1_f = float(v1) if v1 is not None else None
        v2_f = float(v2) if v2 is not None else None
        diff = (v2_f - v1_f) if (v1_f is not None and v2_f is not None) else None
        pct = round(diff / v1_f * 100, 2) if (v1_f and diff is not None) else None
        return {
            "metric": metric,
            "v1_value": v1_f,
            "v2_value": v2_f,
            "difference": diff,
            "pct_difference": pct,
        }

    rows.append(_diff_row("record_count_pr", v1_count_raw, v2_count))
    rows.append({
        "metric": "amount_sample_first_page",
        "v1_value": v1_amount_sample,
        "v2_value": v2_amount,
        "difference": None,
        "pct_difference": None,
    })
    rows.append({
        "metric": "note",
        "v1_value": "v1 amounts from first page only (sample)",
        "v2_value": "v2 amounts from full loaded dataset",
        "difference": None,
        "pct_difference": None,
    })

    return pd.DataFrame(rows, columns=DIFF_COLUMNS)


def run(root=None, force=False):
    root = Path(root or PROJECT_ROOT)
    VALIDATION_DIR.mkdir(parents=True, exist_ok=True)
    REVIEW_DIR.mkdir(parents=True, exist_ok=True)

    gap_path        = root / "data" / "validation" / "fema_pa_gap_report.csv"
    diff_path       = root / "data" / "validation" / "fema_pa_v1_v2_diff_report.csv"
    highval_path    = root / "data" / "review" / "fema_pa_high_value_unresolved.csv"
    logger = setup_logging("validate_fema_pa_coverage")

    if gap_path.exists() and not force:
        logger.info(f"  Validation outputs exist — skipping. Use --force to re-run.")
        return {"pw_coverage": 0, "pw_target": PW_TARGET, "coverage_pass": False,
                "gap_count": 0, "high_value_unresolved": 0, "status": "CACHED"}

    logger.info("Loading validation inputs...")
    df_v2      = _load_parquet(root / "data" / "normalized" / "fema_pa_projects_v2.parquet", logger)
    df_portal  = _load_parquet(root / "data" / "normalized" / "fema_pa_portal_178_pws.parquet", logger)
    df_linkage = _load_csv(root / "data" / "linked" / "fema_178_pw_linkage.csv", logger)

    # 1. 178-PW coverage check
    pw_coverage = len(df_portal) if not df_portal.empty else 0
    coverage_pass = pw_coverage >= PW_TARGET
    logger.info(f"  178-PW coverage: {pw_coverage}/{PW_TARGET} — {'PASS' if coverage_pass else 'BELOW TARGET'}")

    # 2. V1 vs V2 diff
    df_diff = _build_v1_v2_diff(df_v2, logger)
    df_diff.to_csv(diff_path, index=False, encoding="utf-8")
    logger.info(f"  V1/V2 diff report → {diff_path.name}")

    # 3. Gap report: v2 records with no portal match and amount > threshold
    gap_rows = []
    if not df_v2.empty:
        portal_pws = set()
        if not df_portal.empty and "pw_number" in df_portal.columns:
            portal_pws = set(df_portal["pw_number"].astype(str).str.strip())

        for _, r in df_v2.iterrows():
            pw = str(r.get("pw_number", "")).strip()
            amt = pd.to_numeric(r.get("project_amount", 0), errors="coerce") or 0
            if pw not in portal_pws:
                gap_reason = "pw_not_in_portal"
                if not pw:
                    gap_reason = "no_pw_number"
                gap_rows.append({
                    "pw_number":       pw,
                    "disaster_number": r.get("disaster_number", ""),
                    "applicant_name":  r.get("applicant_name", ""),
                    "category":        r.get("category", ""),
                    "project_amount":  amt,
                    "gap_reason":      gap_reason,
                })

    df_gap = pd.DataFrame(gap_rows, columns=GAP_COLUMNS) if gap_rows else pd.DataFrame(columns=GAP_COLUMNS)
    df_gap.to_csv(gap_path, index=False, encoding="utf-8")
    logger.info(f"  Gap report: {len(df_gap):,} rows → {gap_path.name}")

    # 4. High-value unresolved: linkage rows with confidence=none and amount > threshold
    highval_rows = []
    if not df_linkage.empty and "link_confidence" in df_linkage.columns:
        none_mask = df_linkage["link_confidence"] == "none"
        for _, r in df_linkage[none_mask].iterrows():
            amt = pd.to_numeric(r.get("v2_project_amount", 0), errors="coerce") or 0
            if amt >= HIGH_VALUE_THRESHOLD:
                highval_rows.append({
                    "pw_number":        r.get("pw_number", ""),
                    "disaster_number":  r.get("disaster_number", ""),
                    "applicant_name":   r.get("applicant_name", ""),
                    "project_amount":   amt,
                    "link_confidence":  "none",
                    "review_note":      f"High-value (${amt:,.0f}) with no contract/entity match",
                })

    df_highval = pd.DataFrame(highval_rows, columns=HIGH_VALUE_COLUMNS) if highval_rows else pd.DataFrame(columns=HIGH_VALUE_COLUMNS)
    df_highval.to_csv(highval_path, index=False, encoding="utf-8")
    logger.info(f"  High-value unresolved: {len(df_highval):,} → {highval_path.name}")

    logger.info("=" * 60)
    logger.info("FEMA PA VALIDATION SUMMARY")
    logger.info("=" * 60)
    logger.info(f"  178-PW coverage:       {pw_coverage}/{PW_TARGET} — {'PASS' if coverage_pass else 'FAIL'}")
    logger.info(f"  Gap report rows:        {len(df_gap):,}")
    logger.info(f"  High-value unresolved:  {len(df_highval):,}")

    return {
        "pw_coverage": pw_coverage,
        "pw_target": PW_TARGET,
        "coverage_pass": coverage_pass,
        "gap_count": len(df_gap),
        "high_value_unresolved": len(df_highval),
        "status": "OK",
    }


def main():
    parser = argparse.ArgumentParser(description="Validate FEMA PA coverage and generate gap reports")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    result = run(force=args.force)
    print(f"\nFEMA PA validation: {result['pw_coverage']}/{result['pw_target']} PWs, "
          f"{result['gap_count']} gaps, {result['high_value_unresolved']} high-value unresolved")
    return 0


if __name__ == "__main__":
    sys.exit(main())
