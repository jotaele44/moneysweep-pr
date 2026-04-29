"""
Download Puerto Rico Act 60 tax incentive decree holders from DDEC / Hacienda.

Act 60 (consolidating Act 20/22 and others) grants PR tax exemptions to businesses
and individuals. Decree holders that also receive federal contracts represent
dual beneficiaries — PR tax breaks + federal awards — a key investigative signal.

Sources (tried in order):
  1. DDEC open data portal (data.pr.gov)
  2. DDEC Act 60 page (ddec.pr.gov)
  3. PR Treasury (Hacienda) annual incentive report

Output:
  data/staging/processed/pr_act60_decrees.csv

Usage:
  python3 scripts/download_act60.py
  python3 scripts/download_act60.py --force
"""

import argparse
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import requests

from scripts.config import PROJECT_ROOT, setup_logging

ACT60_COLUMNS = [
    "decree_id", "entity_name", "entity_normalized",
    "decree_type",       # "Act 20", "Act 22", "Act 60", "Act 73", etc.
    "effective_date", "expiry_date",
    "individual_flag",   # 1 if individual, 0 if corporate
    "municipality", "industry_code", "source_url",
]

# CKAN API endpoints for data.pr.gov
DATA_PR_GOV_URLS = [
    "https://data.pr.gov/resource/fmnn-uqb7.json",   # incentives dataset (if exists)
    "https://data.pr.gov/resource/act60-decrees.json",
]

# DDEC direct page
DDEC_URLS = [
    "https://ddec.pr.gov/en/act60/",
    "https://www.ddec.pr.gov/en/tax-incentives/",
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
        "Accept": "application/json, text/html, */*",
    })
    return s


def _try_data_pr_gov(session, logger):
    for url in DATA_PR_GOV_URLS:
        logger.info(f"  Trying data.pr.gov: {url}")
        try:
            resp = session.get(url, params={"$limit": 50000}, timeout=30)
            if resp.status_code in (200, 201) and resp.headers.get("Content-Type", "").startswith("application/json"):
                data = resp.json()
                if isinstance(data, list) and len(data) > 0:
                    logger.info(f"  Got {len(data)} records from data.pr.gov")
                    return data
        except Exception as e:
            logger.warning(f"  data.pr.gov attempt failed: {e}")
    return None


def _try_ddec_page(session, logger):
    """Attempt to scrape DDEC Act 60 decree list from HTML page."""
    for url in DDEC_URLS:
        logger.info(f"  Trying DDEC page: {url}")
        try:
            resp = session.get(url, timeout=30)
            if resp.status_code != 200:
                continue
            # Look for embedded JSON or CSV download links
            text = resp.text
            # Check for downloadable file links
            csv_links = re.findall(r'href=["\']([^"\']*\.csv[^"\']*)["\']', text, re.I)
            excel_links = re.findall(r'href=["\']([^"\']*\.xlsx?[^"\']*)["\']', text, re.I)
            if csv_links:
                logger.info(f"  Found CSV link: {csv_links[0]}")
                return ("csv_link", csv_links[0])
            if excel_links:
                logger.info(f"  Found Excel link: {excel_links[0]}")
                return ("excel_link", excel_links[0])
            logger.info("  DDEC page loaded but no data file links found")
        except Exception as e:
            logger.warning(f"  DDEC page attempt failed: {e}")
    return None


def _records_to_df(records, source_url):
    """Convert API records (list of dicts) to output DataFrame."""
    df = pd.DataFrame(records) if records else pd.DataFrame()
    if df.empty:
        return pd.DataFrame(columns=ACT60_COLUMNS)

    # Map whatever columns exist to our schema
    col_map = {
        "decree_id": ["decree_id", "id", "num_decreto", "decreto"],
        "entity_name": ["entity_name", "nombre", "name", "razon_social", "business_name"],
        "decree_type": ["decree_type", "tipo_decreto", "act_type", "ley"],
        "effective_date": ["effective_date", "fecha_efectiva", "start_date", "fecha_inicio"],
        "expiry_date": ["expiry_date", "fecha_expiracion", "end_date", "fecha_fin"],
        "individual_flag": ["individual_flag", "individual", "is_individual"],
        "municipality": ["municipality", "municipio", "ciudad"],
        "industry_code": ["industry_code", "codigo_industria", "naics", "industry"],
    }
    out = {}
    for out_col, candidates in col_map.items():
        for cand in candidates:
            if cand in df.columns:
                out[out_col] = df[cand].fillna("").astype(str)
                break
        if out_col not in out:
            out[out_col] = ""

    result = pd.DataFrame(out)
    result["entity_normalized"] = result["entity_name"].apply(_normalize_name)
    result["source_url"] = source_url

    # Infer decree_type from entity name or flag if not present
    if "decree_type" not in result.columns or result["decree_type"].eq("").all():
        result["decree_type"] = "Act 60"

    for col in ACT60_COLUMNS:
        if col not in result.columns:
            result[col] = ""
    return result[ACT60_COLUMNS]


def _build_manual_template(out_path, logger):
    """Write an empty CSV with instructions when no data is available."""
    logger.warning("  No Act 60 data retrieved from any source.")
    logger.warning("  Manual option:")
    logger.warning("    1. Visit https://ddec.pr.gov/en/act60/")
    logger.warning("    2. Download the decree holder list")
    logger.warning("    3. Save as data/staging/raw/act60/pr_act60_decrees_raw.csv")
    logger.warning("       with columns: entity_name, decree_type, effective_date, municipality")
    pd.DataFrame(columns=ACT60_COLUMNS).to_csv(out_path, index=False, encoding="utf-8")


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
    out_path = root / "data" / "staging" / "processed" / "pr_act60_decrees.csv"
    logger = setup_logging("download_act60")
    logger.info("Starting Act 60 decree download for Puerto Rico...")

    if not force and _file_has_data(out_path):
        rows = len(pd.read_csv(out_path, dtype=str, low_memory=False))
        logger.info(f"  pr_act60_decrees.csv exists ({rows:,} rows) — skipping.")
        return {"rows": rows, "path": str(out_path), "errors": []}

    # Check for manually placed raw file
    manual_path = root / "data" / "staging" / "raw" / "act60" / "pr_act60_decrees_raw.csv"
    if manual_path.exists():
        logger.info(f"  Loading manual file: {manual_path}")
        df_raw = pd.read_csv(manual_path, dtype=str, low_memory=False)
        df_out = _records_to_df(df_raw.to_dict("records"), str(manual_path))
        out_path.parent.mkdir(parents=True, exist_ok=True)
        df_out.to_csv(out_path, index=False, encoding="utf-8")
        logger.info(f"  Written {len(df_out):,} decree records from manual file")
        return {"rows": len(df_out), "path": str(out_path), "errors": []}

    session = _session()
    errors = []

    # Try data.pr.gov API
    records = _try_data_pr_gov(session, logger)
    if records:
        df_out = _records_to_df(records, DATA_PR_GOV_URLS[0])
        out_path.parent.mkdir(parents=True, exist_ok=True)
        df_out.to_csv(out_path, index=False, encoding="utf-8")
        session.close()
        logger.info(f"  Written {len(df_out):,} decree records")
        _log_summary(df_out, logger)
        return {"rows": len(df_out), "path": str(out_path), "errors": []}

    # Try DDEC page for download links
    ddec_result = _try_ddec_page(session, logger)
    if ddec_result:
        link_type, link_url = ddec_result
        base = "https://ddec.pr.gov"
        full_url = link_url if link_url.startswith("http") else base + link_url
        try:
            resp = session.get(full_url, timeout=60)
            resp.raise_for_status()
            if link_type == "csv_link":
                import io
                df_raw = pd.read_csv(io.StringIO(resp.text), dtype=str, low_memory=False)
            else:
                import io
                df_raw = pd.read_excel(io.BytesIO(resp.content), dtype=str)
            df_out = _records_to_df(df_raw.to_dict("records"), full_url)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            df_out.to_csv(out_path, index=False, encoding="utf-8")
            session.close()
            logger.info(f"  Written {len(df_out):,} decree records from DDEC download")
            _log_summary(df_out, logger)
            return {"rows": len(df_out), "path": str(out_path), "errors": []}
        except Exception as e:
            logger.warning(f"  DDEC file download failed: {e}")
            errors.append(str(e))

    session.close()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    _build_manual_template(out_path, logger)
    return {"rows": 0, "path": str(out_path), "errors": errors or ["No data source succeeded"]}


def _log_summary(df, logger):
    logger.info("=" * 60)
    logger.info("ACT 60 SUMMARY")
    logger.info("=" * 60)
    logger.info(f"  Total decrees:    {len(df):,}")
    if "decree_type" in df.columns:
        for dtype, count in df["decree_type"].value_counts().items():
            logger.info(f"    {dtype}: {count:,}")
    logger.info(f"  Unique entities:  {df['entity_normalized'].nunique()}")


def main():
    parser = argparse.ArgumentParser(description="Download Act 60 decree holders for Puerto Rico")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    result = _run(force=args.force)
    print(f"\nAct 60 complete: {result['rows']:,} decrees")
    return 1 if result["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
