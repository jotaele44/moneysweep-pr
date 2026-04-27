"""
Download PR Environmental Quality Board (EQB / Junta de Calidad Ambiental) permit
and compliance data via EPA ECHO ICIS bulk downloads. EPA ECHO mirrors PR air quality
(ICIS-Air) and water discharge (ICIS-NPDES) permits issued under EQB authority.

Cross-referencing against award recipients reveals open environmental violations
that may affect contractor eligibility or project delivery timelines.

Outputs:
  data/staging/processed/pr_eqb_permits.csv

Usage:
  python3 scripts/download_eqb.py
  python3 scripts/download_eqb.py --force
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

# EPA ECHO ICIS bulk data (public, no auth required)
# https://echo.epa.gov/tools/data-downloads
ECHO_SOURCES = {
    "air":   "https://echo.epa.gov/files/echodownloads/ICIS-AIR_downloads.zip",
    "water": "https://echo.epa.gov/files/echodownloads/npdes_downloads.zip",
}

MAX_RETRIES   = 3
RETRY_BACKOFF = [10, 30, 60]
STREAM_CHUNK  = 1024 * 1024

OUTPUT_COLUMNS = [
    "permit_id", "facility_name", "facility_normalized",
    "permit_type", "issued_date", "expiry_date",
    "violation_count", "inspection_count", "state",
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": "ContractSweeper/1.0 (PR EQB research)"})
    return s


def _download_and_extract(session: requests.Session, url: str,
                          permit_type: str, logger) -> pd.DataFrame | None:
    """Download EPA ECHO ZIP and extract the facilities/permits CSV for PR."""
    logger.info(f"  Downloading {permit_type} data: {url}")
    for attempt in range(MAX_RETRIES):
        try:
            resp = session.get(url, timeout=120, stream=True)
            if 400 <= resp.status_code < 500:
                logger.warning(f"  HTTP {resp.status_code} for {permit_type} — skipping")
                return None
            resp.raise_for_status()
            buf = io.BytesIO()
            total = 0
            for chunk in resp.iter_content(chunk_size=STREAM_CHUNK):
                buf.write(chunk)
                total += len(chunk)
            logger.info(f"  Downloaded {total / 1e6:.1f} MB")
            break
        except requests.RequestException as exc:
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_BACKOFF[attempt])
            else:
                logger.error(f"  All retries failed: {exc}")
                return None

    try:
        with zipfile.ZipFile(io.BytesIO(buf.getvalue())) as zf:
            csv_files = [n for n in zf.namelist() if n.lower().endswith(".csv")]
            if not csv_files:
                return None
            # Prefer facilities file; otherwise largest CSV
            fac_file = next(
                (n for n in csv_files if "facilit" in n.lower()), None
            ) or max(csv_files, key=lambda n: zf.getinfo(n).file_size)
            logger.info(f"  Extracting {fac_file}...")
            with zf.open(fac_file) as f:
                df = pd.read_csv(f, dtype=str, low_memory=False)
    except zipfile.BadZipFile as exc:
        logger.error(f"  Bad ZIP: {exc}")
        return None

    # Filter to PR
    state_col = next(
        (c for c in df.columns if c.upper() in ("STATE_CODE", "STATE", "FAC_STATE")),
        None,
    )
    if state_col:
        df = df[df[state_col].str.upper().isin(["PR", "PUERTO RICO", "72"])].copy()
    logger.info(f"  PR {permit_type} facilities: {len(df):,}")
    return df if not df.empty else None


def _build_rows(df: pd.DataFrame, permit_type: str) -> list[dict]:
    col = lambda *cands: next((c for c in cands if c in df.columns), None)

    pid     = col("NPDES_ID", "AIR_ID", "PERMIT_ID", "REGISTRY_ID")
    name    = col("FAC_NAME", "FACILITY_NAME", "NAME")
    issued  = col("PERMIT_ISSUE_DATE", "AIR_PROGRAM_CODE", "ISSUE_DATE")
    expiry  = col("PERMIT_EXPIRATION_DATE", "EXPIRATION_DATE")
    viols   = col("VIOL_CNT", "VIOLATION_COUNT", "NUM_VIOLATIONS")
    insps   = col("INSP_CNT", "INSPECTION_COUNT", "NUM_INSPECTIONS")
    state   = col("FAC_STATE", "STATE_CODE", "STATE")

    rows = []
    for _, r in df.iterrows():
        facility = str(r[name] if name else "")
        rows.append({
            "permit_id":          str(r[pid] if pid else ""),
            "facility_name":      facility,
            "facility_normalized": _normalize_name(facility),
            "permit_type":        permit_type,
            "issued_date":        str(r[issued] if issued else ""),
            "expiry_date":        str(r[expiry] if expiry else ""),
            "violation_count":    int(float(r[viols] or 0)) if viols and pd.notna(r[viols]) else 0,
            "inspection_count":   int(float(r[insps] or 0)) if insps and pd.notna(r[insps]) else 0,
            "state":              str(r[state] if state else "PR"),
        })
    return rows


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------

def run(root: Path = None, force: bool = False) -> dict:
    root = Path(root or PROJECT_ROOT)
    out_path = root / "data" / "staging" / "processed" / "pr_eqb_permits.csv"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    logger = setup_logging("download_eqb", log_dir=root / "data" / "logs")

    if out_path.exists() and not force:
        rows = sum(1 for _ in open(out_path)) - 1
        logger.info(f"  EQB permits: {out_path.name} exists ({rows:,} rows) — skipping.")
        return {"status": "CACHED", "rows": rows}

    session = _session()
    all_rows: list[dict] = []

    for permit_type, url in ECHO_SOURCES.items():
        df = _download_and_extract(session, url, permit_type, logger)
        if df is not None:
            rows = _build_rows(df, permit_type)
            all_rows.extend(rows)
            logger.info(f"  EQB {permit_type}: {len(rows):,} PR facilities")
        else:
            logger.warning(f"  EQB {permit_type}: no data retrieved")

    if not all_rows:
        logger.warning("  No EQB data retrieved — writing empty output")
        pd.DataFrame(columns=OUTPUT_COLUMNS).to_csv(out_path, index=False)
        return {"status": "EMPTY", "rows": 0}

    df_out = pd.DataFrame(all_rows, columns=OUTPUT_COLUMNS)
    df_out = df_out.drop_duplicates(subset=["permit_id", "permit_type"])
    df_out.to_csv(out_path, index=False)

    n = len(df_out)
    viols = (df_out["violation_count"] > 0).sum()
    logger.info(f"  EQB permits: {n:,} rows, {viols:,} with open violations → {out_path.name}")

    return {"status": "OK", "rows": n, "with_violations": int(viols)}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Download PR EQB environmental permit data")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    result = run(force=args.force)
    return 0 if result.get("status") in ("OK", "CACHED") else 1


if __name__ == "__main__":
    sys.exit(main())
