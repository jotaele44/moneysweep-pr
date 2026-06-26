"""
Download federal civilian payroll for Puerto Rico from OPM FedScope.

FedScope is OPM's federal-workforce cube: employment counts and average salary by
agency, location, and occupation. This captures the federal *payroll* footprint
in PR — a government financial flow not represented by the award/grant feeds.

FedScope publishes bulk data files (zipped delimited extracts) rather than a JSON
API; the resource URL is configurable via the ``FEDSCOPE_DATA_URL`` env var.
Network access is required for a live pull — without it this writes a header-only
CSV (live materialization deferred to a networked run).

Output:
  data/staging/processed/pr_federal_payroll.csv

Usage:
  python3 scripts/download_opm_fedscope.py
  python3 scripts/download_opm_fedscope.py --force
"""

from __future__ import annotations

import argparse
import io
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from moneysweep.runtime.base_downloader import build_session
from scripts.config import PROJECT_ROOT, setup_logging

_USER_AGENT = "ContractSweeper/1.0 (PR federal spending research)"
# FedScope employment cube extract (delimited). Override via FEDSCOPE_DATA_URL.
DEFAULT_FEDSCOPE_URL = "https://www.opm.gov/data/datasets/Files/employment_pr.csv"
PR_LOCATION_TOKENS = ("PR", "PUERTO RICO", "72")

OUTPUT_COLUMNS = [
    "agency",
    "location",
    "occupation",
    "employment",
    "average_salary",
    "period",
]

_COL_CANDIDATES = {
    "agency": ["agency", "agysub", "agency_name", "agencyname"],
    "location": ["location", "loc", "state", "locname"],
    "occupation": ["occupation", "occ", "occfam", "occ_name"],
    "employment": ["employment", "count", "emp", "headcount"],
    "average_salary": ["average_salary", "salary", "avgsal", "mean_salary"],
    "period": ["period", "date", "asof", "datecode"],
}


def _try_fetch(url: str, logger) -> pd.DataFrame | None:
    session = build_session(_USER_AGENT, {"Accept": "*/*"})
    try:
        resp = session.get(url, timeout=60)
        if resp.status_code != 200 or not resp.content:
            logger.warning(f"  FedScope source returned HTTP {resp.status_code}")
            return None
        return pd.read_csv(io.BytesIO(resp.content), dtype=str, low_memory=False)
    except Exception as exc:
        logger.warning(f"  Could not fetch FedScope data: {type(exc).__name__}: {exc}")
        return None
    finally:
        session.close()


def _pick(df: pd.DataFrame, candidates: list[str]) -> str | None:
    lower = {c.lower().strip(): c for c in df.columns}
    for cand in candidates:
        if cand in lower:
            return lower[cand]
    return None


def _to_pr_rows(df: pd.DataFrame) -> list[dict]:
    cols = {k: _pick(df, v) for k, v in _COL_CANDIDATES.items()}
    loc_col = cols["location"]
    rows = []
    for _, r in df.iterrows():
        if loc_col is not None:
            loc = str(r.get(loc_col, "")).strip().upper()
            if not any(tok in loc for tok in PR_LOCATION_TOKENS):
                continue
        row = {col: "" for col in OUTPUT_COLUMNS}
        for target, src in cols.items():
            if src is not None:
                row[target] = str(r.get(src, "")).strip()
        rows.append(row)
    return rows


def run(root: Path | None = None, force: bool = False) -> dict:
    root = Path(root or PROJECT_ROOT)
    out_path = root / "data" / "staging" / "processed" / "pr_federal_payroll.csv"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    logger = setup_logging("download_opm_fedscope")

    if not force and out_path.exists():
        existing = pd.read_csv(out_path, dtype=str, low_memory=False)
        if len(existing) > 0:
            logger.info(f"  Cached — {len(existing):,} rows in {out_path.name}")
            return {"rows": len(existing), "path": str(out_path), "status": "CACHED"}

    url = os.environ.get("FEDSCOPE_DATA_URL", DEFAULT_FEDSCOPE_URL)
    logger.info("Fetching PR federal civilian payroll from OPM FedScope...")
    df = _try_fetch(url, logger)
    rows = _to_pr_rows(df) if df is not None else []

    out_df = pd.DataFrame(rows, columns=OUTPUT_COLUMNS)
    out_df.to_csv(out_path, index=False, encoding="utf-8")
    status = "OK" if len(out_df) else "NO_DATA"
    logger.info(f"  {status}: {len(out_df):,} PR federal-payroll records → {out_path.name}")
    return {"rows": len(out_df), "path": str(out_path), "status": status}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="Re-fetch even if output exists")
    args = parser.parse_args()
    result = run(force=args.force)
    print(f"\nOPM FedScope payroll: {result['rows']:,} rows — {result['status']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
