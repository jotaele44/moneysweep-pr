"""
Download Qualified Opportunity Zone (QOZ) designations for Puerto Rico.

Opportunity Zones are a federal capital-gains tax incentive (Treasury/IRS) tied
to designated low-income census tracts; nearly all of PR is designated. This
producer records the designated PR tracts so OZ-linked investment can be joined
to the entity/award layers later. It is distinct from the LIHTC/NMTC place-based
credits already covered.

The authoritative tract list is published by the CDFI Fund as a downloadable
file rather than a JSON API; the resource URL is configurable via the
``OZ_DATA_URL`` env var. Network access is required for a live pull — without it
this writes a header-only CSV (live materialization deferred to a networked run).

Output:
  data/staging/processed/pr_opportunity_zones.csv

Usage:
  python3 scripts/download_opportunity_zones.py
  python3 scripts/download_opportunity_zones.py --force
"""

from __future__ import annotations

import argparse
import io
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from contract_sweeper.runtime.base_downloader import build_session
from scripts.config import PROJECT_ROOT, setup_logging

_USER_AGENT = "ContractSweeper/1.0 (PR federal spending research)"
DEFAULT_OZ_URL = "https://www.cdfifund.gov/sites/cdfi/files/documents/designated-qoz.12.14.18.xlsx"
PR_STATE_FIPS_PREFIX = "72"

OUTPUT_COLUMNS = [
    "census_tract",
    "state",
    "county",
    "tract_type",
    "designation_source",
]


def _try_fetch(url: str, logger) -> pd.DataFrame | None:
    """Best-effort fetch of the designated-QOZ list; None on any failure."""
    session = build_session(_USER_AGENT, {"Accept": "*/*"})
    try:
        resp = session.get(url, timeout=60)
        if resp.status_code != 200 or not resp.content:
            logger.warning(f"  OZ source returned HTTP {resp.status_code}")
            return None
        buf = io.BytesIO(resp.content)
        if url.lower().endswith((".xlsx", ".xls")):
            return pd.read_excel(buf, dtype=str)
        return pd.read_csv(buf, dtype=str)
    except Exception as exc:  # network/parse failure — degrade to empty
        logger.warning(f"  Could not fetch OZ list: {type(exc).__name__}: {exc}")
        return None
    finally:
        session.close()


def _to_pr_rows(df: pd.DataFrame, source: str) -> list[dict]:
    # Find the tract-id column (CDFI sheet header varies across vintages).
    tract_col = next(
        (
            c
            for c in df.columns
            if "tract" in c.lower() or "geoid" in c.lower() or "census" in c.lower()
        ),
        None,
    )
    if tract_col is None:
        return []
    type_col = next((c for c in df.columns if "type" in c.lower()), None)
    rows = []
    for _, r in df.iterrows():
        tract = str(r.get(tract_col, "")).strip()
        if not tract.startswith(PR_STATE_FIPS_PREFIX):
            continue
        rows.append(
            {
                "census_tract": tract,
                "state": "PR",
                "county": tract[2:5] if len(tract) >= 5 else "",
                "tract_type": str(r.get(type_col, "")).strip() if type_col else "",
                "designation_source": source,
            }
        )
    return rows


def run(root: Path | None = None, force: bool = False) -> dict:
    root = Path(root or PROJECT_ROOT)
    out_path = root / "data" / "staging" / "processed" / "pr_opportunity_zones.csv"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    logger = setup_logging("download_opportunity_zones")

    if not force and out_path.exists():
        existing = pd.read_csv(out_path, dtype=str, low_memory=False)
        if len(existing) > 0:
            logger.info(f"  Cached — {len(existing):,} rows in {out_path.name}")
            return {"rows": len(existing), "path": str(out_path), "status": "CACHED"}

    url = os.environ.get("OZ_DATA_URL", DEFAULT_OZ_URL)
    logger.info("Fetching PR Opportunity Zone designations...")
    df = _try_fetch(url, logger)
    rows = _to_pr_rows(df, url) if df is not None else []

    out_df = pd.DataFrame(rows, columns=OUTPUT_COLUMNS)
    out_df.to_csv(out_path, index=False, encoding="utf-8")
    status = "OK" if len(out_df) else "NO_DATA"
    logger.info(f"  {status}: {len(out_df):,} PR OZ tracts → {out_path.name}")
    return {"rows": len(out_df), "path": str(out_path), "status": status}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="Re-fetch even if output exists")
    args = parser.parse_args()
    result = run(force=args.force)
    print(f"\nOpportunity Zones: {result['rows']:,} rows — {result['status']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
