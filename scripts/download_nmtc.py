"""
Download CDFI Fund New Markets Tax Credit (NMTC) allocatee data for Puerto Rico.

NMTC directs private capital into low-income communities. PR allocatees and
investors overlap with federal contractors and LIHTC developers.

Source: CDFI Fund NMTC allocatee list (Excel or CSV)
  https://www.cdfifund.gov/programs-training/programs/new-markets-tax-credit/allocatees

Output:
  data/staging/processed/pr_nmtc_allocations.csv

Usage:
  python3 scripts/download_nmtc.py
  python3 scripts/download_nmtc.py --force
"""

import argparse
import io
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import requests

from scripts.config import PROJECT_ROOT, setup_logging

NMTC_URLS = [
    "https://www.cdfifund.gov/sites/cdfi/files/documents/cdfi-nmtc-allocatees.xlsx",
    "https://www.cdfifund.gov/sites/cdfi/files/documents/nmtc-allocatees.xlsx",
    "https://www.cdfifund.gov/programs-training/programs/new-markets-tax-credit/allocatees",
]

NMTC_COLUMNS = [
    "allocatee_name", "allocatee_normalized", "ein",
    "allocation_year", "allocation_amount",
    "service_area_states", "pr_service_area",
    "city", "state",
]

MAX_RETRIES = 3
RETRY_BACKOFF = [2, 4, 8]


def _normalize_name(name):
    if not name or pd.isna(name):
        return ""
    n = str(name).upper().strip()
    n = re.sub(r"\b(INC\.?|LLC\.?|CORP\.?|LTD\.?|CO\.?|LP\.?|L\.P\.?|L\.L\.C\.?)\b", "", n)
    n = re.sub(r"[^A-Z0-9 ]", " ", n)
    return re.sub(r"\s+", " ", n).strip()


def _session():
    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (compatible; ContractSweeper/1.0)",
        "Accept": "*/*",
    })
    return s


def _try_download_excel(session, logger):
    for url in NMTC_URLS[:2]:
        logger.info(f"  Trying: {url}")
        for attempt in range(MAX_RETRIES):
            try:
                resp = session.get(url, timeout=60)
                if resp.status_code == 404:
                    break
                resp.raise_for_status()
                logger.info(f"  Downloaded {len(resp.content):,} bytes")
                return resp.content
            except requests.RequestException as e:
                if attempt < MAX_RETRIES - 1:
                    time.sleep(RETRY_BACKOFF[attempt])
                else:
                    logger.warning(f"  Failed: {e}")
    return None


def _parse_excel(content, logger):
    try:
        xls = pd.ExcelFile(io.BytesIO(content))
        logger.info(f"  Sheets: {xls.sheet_names}")
        # Use first sheet or one named 'Allocatees'
        sheet = next(
            (s for s in xls.sheet_names if "alloc" in s.lower()),
            xls.sheet_names[0],
        )
        df = pd.read_excel(xls, sheet_name=sheet, dtype=str)
        df.columns = [str(c).strip() for c in df.columns]
        logger.info(f"  Loaded {len(df):,} rows, cols: {list(df.columns[:6])}")
        return df
    except Exception as e:
        logger.error(f"  Excel parse failed: {e}")
        return None


def _filter_pr(df, logger):
    rows = []
    # Check allocatee state or service area for PR
    state_cols = [c for c in df.columns if "state" in c.lower() or "st" == c.lower()]
    area_cols = [c for c in df.columns if "service" in c.lower() or "area" in c.lower()]

    for _, row in df.iterrows():
        is_pr = False
        # Direct PR state check
        for col in state_cols:
            val = str(row.get(col, "")).upper()
            if val.strip() == "PR" or "PUERTO RICO" in val:
                is_pr = True
                break
        # Service area includes PR
        if not is_pr:
            for col in area_cols:
                val = str(row.get(col, "")).upper()
                if " PR" in val or ",PR" in val or "PR," in val or val.strip() == "PR" or "PUERTO RICO" in val:
                    is_pr = True
                    break
        if is_pr:
            rows.append(row)

    result = pd.DataFrame(rows) if rows else pd.DataFrame(columns=df.columns)
    logger.info(f"  PR-related allocatees: {len(result)}")
    return result


def _build_output(df, logger):
    col_map = {
        "allocatee_name": ["Allocatee Name", "CDE Name", "Organization Name", "name"],
        "ein": ["EIN", "Tax ID", "FEIN"],
        "allocation_year": ["Allocation Year", "Year", "Round"],
        "allocation_amount": ["Allocation Amount", "Total Allocation", "Amount"],
        "service_area_states": ["Service Area States", "States Served", "Service Area"],
        "city": ["City", "Allocatee City"],
        "state": ["State", "Allocatee State", "ST"],
    }
    out = pd.DataFrame()
    for out_col, candidates in col_map.items():
        for cand in candidates:
            matches = [c for c in df.columns if c.strip().lower() == cand.lower()]
            if matches:
                out[out_col] = df[matches[0]].fillna("").astype(str)
                break
        if out_col not in out.columns:
            out[out_col] = ""

    out["allocatee_normalized"] = out["allocatee_name"].apply(_normalize_name)
    out["pr_service_area"] = out["service_area_states"].apply(
        lambda x: 1 if "PR" in str(x).upper() or "PUERTO" in str(x).upper() else 0
    )

    for col in NMTC_COLUMNS:
        if col not in out.columns:
            out[col] = ""
    return out[NMTC_COLUMNS]


def _file_has_data(path):
    if not path.exists():
        return False
    try:
        return len(pd.read_csv(path, dtype=str, nrows=2)) > 0
    except Exception:
        return False


def run(root=None):
    return _run(root=root, force=False)


def _run(root=None, force=False):
    if root is None:
        root = PROJECT_ROOT
    out_path = root / "data" / "staging" / "processed" / "pr_nmtc_allocations.csv"
    logger = setup_logging("download_nmtc")
    logger.info("Starting NMTC allocatee download for Puerto Rico (CDFI Fund)...")

    if not force and _file_has_data(out_path):
        rows = len(pd.read_csv(out_path, dtype=str, low_memory=False))
        logger.info(f"  pr_nmtc_allocations.csv exists ({rows:,} rows) — skipping.")
        return {"rows": rows, "path": str(out_path), "errors": []}

    # Check for manually placed file
    manual_dir = root / "data" / "staging" / "raw" / "nmtc"
    manual_files = list(manual_dir.glob("*.xlsx")) + list(manual_dir.glob("*.xls")) if manual_dir.exists() else []

    session = _session()
    content = _try_download_excel(session, logger)
    session.close()

    if content is None and manual_files:
        logger.info(f"  Using manual file: {manual_files[0]}")
        content = manual_files[0].read_bytes()

    if content is None:
        logger.warning("  Could not download NMTC data.")
        logger.warning("  Manual: download allocatee list from https://www.cdfifund.gov/programs-training/programs/new-markets-tax-credit/allocatees")
        logger.warning("  Save as data/staging/raw/nmtc/nmtc_allocatees.xlsx")
        pd.DataFrame(columns=NMTC_COLUMNS).to_csv(out_path, index=False, encoding="utf-8")
        return {"rows": 0, "path": str(out_path), "errors": ["Download failed"]}

    df_raw = _parse_excel(content, logger)
    if df_raw is None:
        pd.DataFrame(columns=NMTC_COLUMNS).to_csv(out_path, index=False, encoding="utf-8")
        return {"rows": 0, "path": str(out_path), "errors": ["Parse failed"]}

    df_pr = _filter_pr(df_raw, logger)
    df_out = _build_output(df_pr, logger)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df_out.to_csv(out_path, index=False, encoding="utf-8")

    total_alloc = pd.to_numeric(df_out["allocation_amount"], errors="coerce").fillna(0).sum()
    logger.info("=" * 60)
    logger.info("NMTC SUMMARY")
    logger.info("=" * 60)
    logger.info(f"  PR-related allocatees: {len(df_out)}")
    logger.info(f"  Total allocation:      ${total_alloc:,.0f}")

    return {"rows": len(df_out), "path": str(out_path), "errors": []}


def main():
    parser = argparse.ArgumentParser(description="Download NMTC allocatees for Puerto Rico")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    result = _run(force=args.force)
    print(f"\nNMTC complete: {result['rows']:,} PR-related allocatees")
    return 1 if result["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
