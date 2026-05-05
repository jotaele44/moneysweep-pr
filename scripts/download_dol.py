"""
Download DOL (Department of Labor) enforcement data for Puerto Rico.

Covers:
  - WHD (Wage and Hour Division) FLSA violations via WHISARD database
  - OSHA inspections and citations for PR establishments
  - Both are bulk CSV downloads from enforcedata.dol.gov, filtered for PR

The enforcement layer adds a compliance signal: federal contractors with open
DOL violations represent elevated financial-flow risk.

Sources:
  1. DOL WHISARD (WHD) enforcement: https://enforcedata.dol.gov/views/data_summary.php
  2. OSHA enforcement data: https://www.osha.gov/ords/imis/establishment.html
  3. DOL Open Data (data.dol.gov) CKAN API fallback

Output:
  data/staging/processed/pr_dol_enforcement.csv

Usage:
  python3 scripts/download_dol.py [--force]
"""

import argparse
import io
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import requests

from scripts.config import PROCESSED_DIR, PROJECT_ROOT, setup_logging

DOL_ENFORCE_BASE = "https://enforcedata.dol.gov"
DOL_OPENDATA_URL = "https://data.dol.gov/api/3/action/package_search"
OSHA_DATA_BASE = "https://www.osha.gov/ords/imis"

# Known bulk CSV endpoints for WHD/OSHA enforcement data
WHD_CSV_URL = "https://enforcedata.dol.gov/xml/full_whd.zip"
OSHA_CSV_URLS = [
    "https://www.osha.gov/ords/imis/establishment.zip",
    "https://enforcement.osha.gov/data/osha_inspection.csv",
]

PAGE_SLEEP = 0.5
MAX_RETRIES = 3
RETRY_BACKOFF = [5, 15, 30]

DOL_COLUMNS = [
    "case_id", "enforcement_type",
    "employer_name", "employer_normalized",
    "city", "state", "naics_code",
    "violation_type", "penalty_amount", "back_wages",
    "investigation_start", "findings_date",
    "employees_affected", "source_doc",
]


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": "ContractSweeper/1.0 (PR DOL enforcement research)",
        "Accept": "application/json, text/csv, application/zip",
    })
    return s


def _get(session: requests.Session, url: str, params: dict, logger,
         stream: bool = False) -> requests.Response | None:
    for attempt in range(MAX_RETRIES):
        try:
            resp = session.get(url, params=params, timeout=120, stream=stream)
            if resp.status_code == 429:
                time.sleep(60)
                continue
            if 400 <= resp.status_code < 500:
                logger.warning(f"  HTTP {resp.status_code} for {url}")
                return None
            resp.raise_for_status()
            time.sleep(PAGE_SLEEP)
            return resp
        except requests.RequestException as exc:
            if attempt < MAX_RETRIES - 1:
                wait = RETRY_BACKOFF[attempt]
                logger.warning(f"  Attempt {attempt+1} failed ({exc}) — retrying in {wait}s")
                time.sleep(wait)
            else:
                logger.error(f"  All {MAX_RETRIES} attempts failed: {exc}")
    return None


def _normalize_name(name: str) -> str:
    import re
    if not name:
        return ""
    n = re.sub(r"[^\w\s]", " ", name.upper())
    n = re.sub(r"\s+", " ", n).strip()
    suffixes = {"INC", "LLC", "LLP", "CORP", "CO", "LTD", "LP", "THE", "OF", "DBA"}
    tokens = n.split()
    while tokens and tokens[-1] in suffixes:
        tokens.pop()
    return " ".join(tokens)


def _filter_pr(df: pd.DataFrame, state_cols: list[str]) -> pd.DataFrame:
    mask = pd.Series([False] * len(df), index=df.index)
    for col in state_cols:
        if col in df.columns:
            mask |= df[col].astype(str).str.upper().isin(["PR", "PUERTO RICO", "72"])
    return df[mask]


def _fetch_whd_bulk(session: requests.Session, logger) -> list[dict]:
    rows = []
    # Try the DOL enforce data summary page for WHD CSV links
    resp = _get(session, f"{DOL_ENFORCE_BASE}/views/data_summary.php", {}, logger)
    if resp:
        import re
        links = re.findall(r'href=["\']([^"\']*whd[^"\']*\.(?:csv|zip))["\']',
                           resp.text, re.IGNORECASE)
        for link in links[:3]:
            if not link.startswith("http"):
                link = f"{DOL_ENFORCE_BASE}/{link.lstrip('/')}"
            try:
                file_resp = session.get(link, timeout=120)
                if file_resp.status_code != 200:
                    continue
                if link.endswith(".zip"):
                    import zipfile
                    with zipfile.ZipFile(io.BytesIO(file_resp.content)) as zf:
                        for name in zf.namelist():
                            if name.endswith(".csv"):
                                df = pd.read_csv(
                                    io.BytesIO(zf.read(name)),
                                    dtype=str, low_memory=False, encoding="latin-1"
                                )
                                df = _filter_pr(df, ["state_cd", "state", "st_cd", "zip_cd"])
                                if len(df) > 0:
                                    df["source_doc"] = link
                                    df["enforcement_type"] = "WHD"
                                    rows.extend(df.to_dict("records"))
                                    logger.info(f"  WHD zip {name}: {len(df)} PR rows")
                else:
                    df = pd.read_csv(
                        io.BytesIO(file_resp.content), dtype=str, low_memory=False,
                        encoding="latin-1"
                    )
                    df = _filter_pr(df, ["state_cd", "state", "st_cd"])
                    if len(df) > 0:
                        df["source_doc"] = link
                        df["enforcement_type"] = "WHD"
                        rows.extend(df.to_dict("records"))
                        logger.info(f"  WHD CSV: {len(df)} PR rows")
            except Exception as e:
                logger.debug(f"  WHD fetch failed for {link}: {e}")
            if rows:
                break
    return rows


def _fetch_osha_bulk(session: requests.Session, logger) -> list[dict]:
    rows = []
    # OSHA inspection data — bulk download
    for url in OSHA_CSV_URLS:
        try:
            resp = session.get(url, timeout=180)
            if resp.status_code != 200:
                continue
            if url.endswith(".zip"):
                import zipfile
                with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
                    for name in zf.namelist():
                        if name.endswith(".csv"):
                            df = pd.read_csv(
                                io.BytesIO(zf.read(name)), dtype=str, low_memory=False,
                                encoding="latin-1"
                            )
                            df = _filter_pr(df, ["state", "site_state", "state_id"])
                            if len(df) > 0:
                                df["source_doc"] = url
                                df["enforcement_type"] = "OSHA"
                                rows.extend(df.to_dict("records"))
                                logger.info(f"  OSHA zip {name}: {len(df)} PR rows")
            else:
                df = pd.read_csv(
                    io.BytesIO(resp.content), dtype=str, low_memory=False, encoding="latin-1"
                )
                df = _filter_pr(df, ["state", "site_state"])
                if len(df) > 0:
                    df["source_doc"] = url
                    df["enforcement_type"] = "OSHA"
                    rows.extend(df.to_dict("records"))
                    logger.info(f"  OSHA CSV: {len(df)} PR rows")
        except Exception as e:
            logger.debug(f"  OSHA fetch failed for {url}: {e}")
        if rows:
            break
    return rows


def _fetch_dol_opendata(session: requests.Session, logger) -> list[dict]:
    rows = []
    try:
        resp = _get(session, DOL_OPENDATA_URL,
                    {"q": "whd osha enforcement violations puerto rico", "rows": 10}, logger)
        if not resp:
            return rows
        data = resp.json()
        packages = data.get("result", {}).get("results", [])
        for pkg in packages:
            for resource in pkg.get("resources", []):
                url = resource.get("url", "")
                fmt = resource.get("format", "").lower()
                if fmt == "csv" and url:
                    try:
                        file_resp = session.get(url, timeout=120)
                        if file_resp.status_code == 200:
                            df = pd.read_csv(
                                io.BytesIO(file_resp.content), dtype=str,
                                low_memory=False, encoding="latin-1"
                            )
                            df = _filter_pr(df, ["state", "state_cd", "state_id"])
                            if len(df) > 0:
                                df["source_doc"] = url
                                rows.extend(df.to_dict("records"))
                                logger.info(f"  DOL Open Data: {len(df)} PR rows")
                    except Exception as e:
                        logger.debug(f"  Could not fetch {url}: {e}")
    except Exception as e:
        logger.warning(f"  DOL Open Data search failed: {e}")
    return rows


def _normalize_records(all_rows: list[dict], logger) -> pd.DataFrame:
    if not all_rows:
        return pd.DataFrame(columns=DOL_COLUMNS)

    df = pd.json_normalize(all_rows)

    rename = {}
    for col in df.columns:
        cl = col.lower().replace(" ", "_")
        if ("case" in cl or "activity" in cl or "inspection" in cl) and "case_id" not in rename.values():
            rename[col] = "case_id"
        elif "enforcement_type" == col:
            rename[col] = "enforcement_type"
        elif ("employer" in cl or "establishment" in cl or "legal_name" in cl
              ) and "name" in cl and "employer_name" not in rename.values():
            rename[col] = "employer_name"
        elif ("city" in cl or "city_nm" in cl) and "city" not in rename.values():
            rename[col] = "city"
        elif col.lower() in ("state_cd", "state", "st_cd") and "state" not in rename.values():
            rename[col] = "state"
        elif "naics" in cl and "naics_code" not in rename.values():
            rename[col] = "naics_code"
        elif ("violat" in cl or "finding" in cl) and "type" in cl and "violation_type" not in rename.values():
            rename[col] = "violation_type"
        elif "penalty" in cl and "penalty_amount" not in rename.values():
            rename[col] = "penalty_amount"
        elif ("back_wage" in cl or "bw_" in cl) and "back_wages" not in rename.values():
            rename[col] = "back_wages"
        elif ("investigation" in cl or "open_date" in cl) and "investigation_start" not in rename.values():
            rename[col] = "investigation_start"
        elif ("findings" in cl or "close_date" in cl) and "findings_date" not in rename.values():
            rename[col] = "findings_date"
        elif ("employee" in cl or "worker" in cl) and "count" in cl and "employees_affected" not in rename.values():
            rename[col] = "employees_affected"

    df = df.rename(columns=rename)

    if "employer_name" in df.columns:
        df["employer_normalized"] = df["employer_name"].apply(
            lambda x: _normalize_name(str(x or ""))
        )
    else:
        df["employer_normalized"] = ""

    for col in DOL_COLUMNS:
        if col not in df.columns:
            df[col] = ""

    logger.info(f"  Normalized {len(df):,} DOL enforcement records")
    return df[DOL_COLUMNS]


def run(root: Path = None, force: bool = False) -> dict:
    if root is None:
        root = PROJECT_ROOT
    root = Path(root)
    out_dir = root / "data" / "staging" / "processed"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "pr_dol_enforcement.csv"

    logger = setup_logging("download_dol")

    if not force and out_path.exists():
        existing = pd.read_csv(out_path, dtype=str, low_memory=False)
        if len(existing) > 0:
            logger.info(f"  Cached — {len(existing):,} rows in {out_path.name}")
            return {"rows": len(existing), "path": str(out_path), "status": "CACHED"}

    session = _session()
    all_rows: list[dict] = []

    logger.info("  Fetching WHD (wage-hour) enforcement data...")
    whd_rows = _fetch_whd_bulk(session, logger)
    all_rows.extend(whd_rows)

    logger.info("  Fetching OSHA inspection data...")
    osha_rows = _fetch_osha_bulk(session, logger)
    all_rows.extend(osha_rows)

    if not all_rows:
        logger.info("  Trying DOL Open Data portal...")
        dol_rows = _fetch_dol_opendata(session, logger)
        all_rows.extend(dol_rows)

    session.close()

    if not all_rows:
        logger.warning(
            "  No DOL enforcement data retrieved. Writing empty schema.\n"
            "  Manual alternative: https://enforcedata.dol.gov/views/data_summary.php"
        )
        pd.DataFrame(columns=DOL_COLUMNS).to_csv(out_path, index=False, encoding="utf-8")
        return {"rows": 0, "path": str(out_path), "status": "EMPTY"}

    df = _normalize_records(all_rows, logger)
    df.to_csv(out_path, index=False, encoding="utf-8")
    logger.info(f"  Written: {out_path.name} ({len(df):,} rows)")
    return {"rows": len(df), "path": str(out_path), "status": "OK"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Download DOL WHD + OSHA enforcement data for PR")
    parser.add_argument("--force", action="store_true", help="Re-download even if cached")
    args = parser.parse_args()
    result = run(force=args.force)
    print(f"\nDOL enforcement: {result['rows']:,} rows — {result['status']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
