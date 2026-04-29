"""
Download HUD Low-Income Housing Tax Credit (LIHTC) project data for Puerto Rico.

LIHTC is the primary federal mechanism for affordable housing construction.
PR developers and general contractors who receive LIHTC allocations overlap
significantly with CDBG-DR and federal contract recipients.

Source: HUD User LIHTC Public Use Database (annual ZIP/CSV)
  https://www.huduser.gov/portal/datasets/lihtc/LIHTCPUB.zip

Output:
  data/staging/processed/pr_lihtc_projects.csv

Usage:
  python3 scripts/download_lihtc.py
  python3 scripts/download_lihtc.py --force
"""

import argparse
import io
import re
import sys
import time
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import requests

from scripts.config import PROJECT_ROOT, setup_logging

LIHTC_ZIP_URLS = [
    "https://www.huduser.gov/portal/datasets/lihtc/LIHTCPUB.zip",
    "https://www.huduser.gov/portal/datasets/lihtc/lihtcpub.zip",
]

LIHTC_COLUMNS = [
    "hud_id", "proj_nm", "proj_add", "proj_cty", "proj_zip",
    "county", "yr_pis", "n_units", "n_lihtc_units", "type",
    "allocamt", "proj_own_nm", "dev_nm", "gen_contractor_nm", "syndicator_nm",
    "proj_own_nm_normalized", "dev_nm_normalized", "gen_contractor_nm_normalized",
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


def _download_zip(session, logger):
    for url in LIHTC_ZIP_URLS:
        logger.info(f"  Trying: {url}")
        for attempt in range(MAX_RETRIES):
            try:
                resp = session.get(url, timeout=120)
                if resp.status_code == 404:
                    logger.warning(f"  404 — trying next URL")
                    break
                resp.raise_for_status()
                logger.info(f"  Downloaded {len(resp.content):,} bytes")
                return resp.content
            except requests.RequestException as e:
                if attempt < MAX_RETRIES - 1:
                    wait = RETRY_BACKOFF[attempt]
                    logger.warning(f"  Attempt {attempt + 1} failed ({e}) — retrying in {wait}s")
                    time.sleep(wait)
                else:
                    logger.warning(f"  Failed: {e}")
    return None


def _parse_zip(zip_bytes, logger):
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            csv_names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
            if not csv_names:
                # Try DBF or other formats
                logger.warning(f"  ZIP contents: {zf.namelist()}")
                return None
            csv_name = csv_names[0]
            logger.info(f"  Reading {csv_name} from ZIP...")
            with zf.open(csv_name) as f:
                df = pd.read_csv(f, dtype=str, low_memory=False, encoding="latin-1")
            logger.info(f"  Loaded {len(df):,} rows, columns: {list(df.columns[:8])}")
            return df
    except Exception as e:
        logger.error(f"  Failed to parse ZIP: {e}")
        return None


def _filter_pr(df, logger):
    # State column is typically 'st' or 'state' with value 'PR'
    for col in ("st", "state", "STATE", "ST"):
        if col in df.columns:
            pr = df[df[col].str.strip().str.upper() == "PR"].copy()
            logger.info(f"  Filtered to PR: {len(pr):,} projects (column '{col}')")
            return pr
    logger.warning("  No state column found — returning all rows")
    return df.copy()


def _build_output(df, logger):
    # Map HUD column names to our schema (column names vary by year)
    col_map = {
        "hud_id": ["hud_id", "HUD_ID", "project_id"],
        "proj_nm": ["proj_nm", "PROJ_NM", "project_name", "proj_name"],
        "proj_add": ["proj_add", "PROJ_ADD", "address"],
        "proj_cty": ["proj_cty", "PROJ_CTY", "city"],
        "proj_zip": ["proj_zip", "PROJ_ZIP", "zip"],
        "county": ["county", "COUNTY", "cnty_nm"],
        "yr_pis": ["yr_pis", "YR_PIS", "placed_in_service_year"],
        "n_units": ["n_units", "N_UNITS", "total_units"],
        "n_lihtc_units": ["n_lihtc_units", "N_LIHTC_UNITS", "lihtc_units"],
        "type": ["type", "TYPE", "proj_type"],
        "allocamt": ["allocamt", "ALLOCAMT", "allocation_amount", "alloc_amt"],
        "proj_own_nm": ["proj_own_nm", "PROJ_OWN_NM", "owner_name", "owner"],
        "dev_nm": ["dev_nm", "DEV_NM", "developer_name", "developer"],
        "gen_contractor_nm": ["gen_contractor_nm", "GEN_CONTRACTOR_NM", "general_contractor", "gc_name"],
        "syndicator_nm": ["syndicator_nm", "SYNDICATOR_NM", "syndicator"],
    }
    out = pd.DataFrame()
    for out_col, candidates in col_map.items():
        for cand in candidates:
            if cand in df.columns:
                out[out_col] = df[cand].fillna("").astype(str)
                break
        if out_col not in out.columns:
            out[out_col] = ""

    out["proj_own_nm_normalized"] = out["proj_own_nm"].apply(_normalize_name)
    out["dev_nm_normalized"] = out["dev_nm"].apply(_normalize_name)
    out["gen_contractor_nm_normalized"] = out["gen_contractor_nm"].apply(_normalize_name)

    for col in LIHTC_COLUMNS:
        if col not in out.columns:
            out[col] = ""
    return out[LIHTC_COLUMNS]


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
    out_path = root / "data" / "staging" / "processed" / "pr_lihtc_projects.csv"
    logger = setup_logging("download_lihtc")
    logger.info("Starting LIHTC download for Puerto Rico (HUD User database)...")

    if not force and _file_has_data(out_path):
        rows = len(pd.read_csv(out_path, dtype=str, low_memory=False))
        logger.info(f"  pr_lihtc_projects.csv exists ({rows:,} rows) — skipping. Use --force to re-download.")
        return {"rows": rows, "path": str(out_path), "errors": []}

    session = _session()
    zip_bytes = _download_zip(session, logger)
    session.close()

    if not zip_bytes:
        logger.warning("  Could not download LIHTC ZIP — writing empty file.")
        logger.warning("  Manual: download from https://www.huduser.gov/portal/datasets/lihtc.html")
        logger.warning("  and save as data/staging/raw/lihtc/LIHTCPUB.zip")
        # Check for manually placed file
        manual = root / "data" / "staging" / "raw" / "lihtc" / "LIHTCPUB.zip"
        if manual.exists():
            logger.info(f"  Found manual file: {manual}")
            zip_bytes = manual.read_bytes()
        else:
            pd.DataFrame(columns=LIHTC_COLUMNS).to_csv(out_path, index=False, encoding="utf-8")
            return {"rows": 0, "path": str(out_path), "errors": ["ZIP download failed"]}

    df_raw = _parse_zip(zip_bytes, logger)
    if df_raw is None:
        pd.DataFrame(columns=LIHTC_COLUMNS).to_csv(out_path, index=False, encoding="utf-8")
        return {"rows": 0, "path": str(out_path), "errors": ["ZIP parse failed"]}

    df_pr = _filter_pr(df_raw, logger)
    df_out = _build_output(df_pr, logger)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df_out.to_csv(out_path, index=False, encoding="utf-8")

    total_alloc = pd.to_numeric(df_out["allocamt"], errors="coerce").fillna(0).sum()
    logger.info("=" * 60)
    logger.info("LIHTC SUMMARY")
    logger.info("=" * 60)
    logger.info(f"  PR projects:        {len(df_out):,}")
    logger.info(f"  Total allocation:   ${total_alloc:,.0f}")
    logger.info(f"  Unique developers:  {df_out['dev_nm_normalized'].nunique()}")

    return {"rows": len(df_out), "path": str(out_path), "errors": []}


def main():
    parser = argparse.ArgumentParser(description="Download LIHTC projects for Puerto Rico")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    result = _run(force=args.force)
    print(f"\nLIHTC complete: {result['rows']:,} PR projects")
    return 1 if result["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
