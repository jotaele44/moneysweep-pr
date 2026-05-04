"""
Download USACE Section 404/Section 10 permit data for Puerto Rico via EPA ECHO.
EPA ECHO mirrors USACE ORM permit data as bulk CSVs — no auth required.

PR falls under USACE Jacksonville District jurisdiction.
Permits are required for dredge/fill in wetlands (§404) and work in navigable
waters (§10). Cross-referencing against award recipients reveals which contractors
have (or lack) required environmental permits for their projects.

Outputs:
  data/staging/raw/usace/pr_usace_permits_raw.csv
  data/staging/processed/pr_usace_permits.csv

Usage:
  python3 scripts/download_usace_permits.py
  python3 scripts/download_usace_permits.py --force
"""

import argparse
import io
import sys
import time
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import requests

from scripts.config import PROCESSED_DIR, PROJECT_ROOT, setup_logging
from scripts.build_unified_master import _normalize_name

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# EPA ECHO bulk data downloads — USACE/404 permit data
# https://echo.epa.gov/tools/data-downloads (public, no auth)
ECHO_PERMITS_URL = (
    "https://echo.epa.gov/files/echodownloads/USACE_PERMITS.zip"
)

MAX_RETRIES   = 3
RETRY_BACKOFF = [10, 30, 60]
STREAM_CHUNK  = 1024 * 1024  # 1MB chunks

OUTPUT_COLUMNS = [
    "permit_id", "permit_type", "applicant_name", "applicant_normalized",
    "issued_date", "expiry_date", "project_description",
    "state", "county", "status", "violation_flag",
]

# ---------------------------------------------------------------------------
# Download helpers
# ---------------------------------------------------------------------------

def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": "ContractSweeper/1.0 (PR permit research)"})
    return s


def _download_zip(session: requests.Session, url: str,
                  raw_path: Path, logger) -> bytes | None:
    """Stream-download a ZIP and return contents of the largest CSV inside."""
    logger.info(f"  Downloading {url}...")
    for attempt in range(MAX_RETRIES):
        try:
            resp = session.get(url, timeout=120, stream=True)
            if 400 <= resp.status_code < 500:
                logger.error(f"  HTTP {resp.status_code}: {url}")
                return None
            resp.raise_for_status()
            buf = io.BytesIO()
            total = 0
            for chunk in resp.iter_content(chunk_size=STREAM_CHUNK):
                buf.write(chunk)
                total += len(chunk)
            logger.info(f"  Downloaded {total / 1e6:.1f} MB")
            return buf.getvalue()
        except requests.RequestException as exc:
            if attempt < MAX_RETRIES - 1:
                wait = RETRY_BACKOFF[attempt]
                logger.warning(f"  Attempt {attempt+1} failed ({exc}) — retrying in {wait}s")
                time.sleep(wait)
            else:
                logger.error(f"  All retries failed: {exc}")
    return None


def _extract_csv_from_zip(content: bytes, logger) -> pd.DataFrame | None:
    """Extract the main CSV from a ZIP archive."""
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            csv_files = [n for n in zf.namelist() if n.lower().endswith(".csv")]
            if not csv_files:
                logger.error("  No CSV files found in ZIP")
                return None
            # Pick largest CSV
            target = max(csv_files, key=lambda n: zf.getinfo(n).file_size)
            logger.info(f"  Extracting {target} ({zf.getinfo(target).file_size / 1e6:.1f} MB)...")
            with zf.open(target) as f:
                return pd.read_csv(f, dtype=str, low_memory=False)
    except zipfile.BadZipFile as exc:
        logger.error(f"  Bad ZIP file: {exc}")
        return None


# ---------------------------------------------------------------------------
# Transform
# ---------------------------------------------------------------------------

def _filter_pr(df: pd.DataFrame, logger) -> pd.DataFrame:
    """Keep only Puerto Rico records."""
    state_col = next(
        (c for c in df.columns if "state" in c.lower() and "province" not in c.lower()),
        None,
    )
    if state_col is None:
        logger.warning("  No state column found — returning all records")
        return df
    mask = df[state_col].str.upper().isin(["PR", "PUERTO RICO", "72"])
    logger.info(f"  PR filter: {mask.sum():,} of {len(df):,} records")
    return df[mask].copy()


def _build_output(df: pd.DataFrame) -> pd.DataFrame:
    """Map raw ECHO columns to canonical schema."""
    col = lambda *cands: next(
        (c for c in cands if c in df.columns), None
    )

    permit_id   = col("PERMIT_ID", "ACTIVITY_ID", "permit_id", "PermitID")
    permit_type = col("PERMIT_TYPE", "ACTIVITY_TYPE_CODE", "PermitType")
    applicant   = col("APPLICANT_NAME", "OWNER_NAME", "ApplicantName")
    issued      = col("ISSUED_DATE", "ISSUE_DATE", "IssuedDate")
    expiry      = col("EXPIRATION_DATE", "EXPIRY_DATE", "ExpirationDate")
    desc        = col("PROJECT_DESCRIPTION", "DESCRIPTION", "Description")
    state       = col("STATE_CODE", "STATE", "State")
    county      = col("COUNTY_NAME", "COUNTY", "County")
    status      = col("PERMIT_STATUS", "STATUS", "Status")

    rows = []
    for _, r in df.iterrows():
        name = str(r[applicant] if applicant else "")
        rows.append({
            "permit_id":           str(r[permit_id] if permit_id else ""),
            "permit_type":         str(r[permit_type] if permit_type else ""),
            "applicant_name":      name,
            "applicant_normalized": _normalize_name(name),
            "issued_date":         str(r[issued] if issued else ""),
            "expiry_date":         str(r[expiry] if expiry else ""),
            "project_description": str(r[desc] if desc else "")[:200],
            "state":               str(r[state] if state else ""),
            "county":              str(r[county] if county else ""),
            "status":              str(r[status] if status else ""),
            "violation_flag":      0,
        })
    return pd.DataFrame(rows, columns=OUTPUT_COLUMNS)


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------

def run(root: Path = None, force: bool = False) -> dict:
    root = Path(root or PROJECT_ROOT)
    raw_dir  = root / "data" / "staging" / "raw" / "usace"
    out_path = root / "data" / "staging" / "processed" / "pr_usace_permits.csv"
    raw_dir.mkdir(parents=True, exist_ok=True)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    logger = setup_logging("download_usace_permits", log_dir=root / "data" / "logs")

    if out_path.exists() and not force:
        rows = sum(1 for _ in open(out_path)) - 1
        logger.info(f"  USACE permits: {out_path.name} exists ({rows:,} rows) — skipping.")
        return {"status": "CACHED", "rows": rows}

    session = _session()
    content = _download_zip(session, ECHO_PERMITS_URL, raw_dir, logger)

    if content is None:
        logger.warning("  USACE ZIP download failed — writing empty output")
        pd.DataFrame(columns=OUTPUT_COLUMNS).to_csv(out_path, index=False)
        return {"status": "EMPTY", "rows": 0}

    raw_df = _extract_csv_from_zip(content, logger)
    if raw_df is None or raw_df.empty:
        logger.warning("  No data extracted from ZIP")
        pd.DataFrame(columns=OUTPUT_COLUMNS).to_csv(out_path, index=False)
        return {"status": "EMPTY", "rows": 0}

    pr_df = _filter_pr(raw_df, logger)
    if pr_df.empty:
        logger.warning("  No PR records found in USACE data")
        pd.DataFrame(columns=OUTPUT_COLUMNS).to_csv(out_path, index=False)
        return {"status": "EMPTY", "rows": 0}

    out_df = _build_output(pr_df)
    out_df.to_csv(out_path, index=False)
    rows = len(out_df)
    logger.info(f"  USACE permits: {rows:,} PR records → {out_path.name}")

    return {"status": "OK", "rows": rows}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Download USACE permit data for Puerto Rico")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    result = run(force=args.force)
    return 0 if result.get("status") in ("OK", "CACHED") else 1


if __name__ == "__main__":
    sys.exit(main())
