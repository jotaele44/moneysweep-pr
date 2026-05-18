"""
Download NFIP (National Flood Insurance Program) claims for Puerto Rico via OpenFEMA.

Post-Maria (2017) flood claims are the largest single insurance payout event in PR
history. This dataset maps the geographic and financial scope of flood damage and
can be cross-referenced with FEMA PA contractor award locations.

Source: OpenFEMA API — fimaNfipClaims dataset (anonymized, zip/county level)

Output:
  data/staging/processed/pr_nfip_claims.csv

Usage:
  python3 scripts/download_nfip.py
  python3 scripts/download_nfip.py --force
"""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import requests

from scripts.config import PROCESSED_DIR, PROJECT_ROOT, setup_logging

OPENFEMA_URL = "https://www.fema.gov/api/open/v2/fimaNfipClaims"
PAGE_SIZE = 10_000
MAX_RETRIES = 3
RETRY_BACKOFF = [2, 4, 8]
PAGE_SLEEP = 0.5

NFIP_COLUMNS = [
    "reportedCity", "reportedZipCode", "countyCode", "floodZone",
    "occupancyType", "dateOfLoss", "yearOfLoss",
    "totalBuildingInsuranceCoverage", "totalContentsInsuranceCoverage",
    "amountPaidOnBuildingClaim", "amountPaidOnContentsClaim",
    "buildingDamageAmount", "contentsDamageAmount",
    "originalNBDate",
]

OUTPUT_COLUMNS = [
    "reported_city", "reported_zip", "county_code", "flood_zone",
    "occupancy_type", "date_of_loss", "year_of_loss",
    "building_coverage", "contents_coverage",
    "paid_building", "paid_contents",
    "building_damage", "contents_damage",
    "policy_start_date",
]


def _session():
    s = requests.Session()
    s.headers.update({"User-Agent": "ContractSweeper/1.0", "Accept": "application/json"})
    return s


def _fetch_page(session, skip, logger):
    params = {
        "$filter": "state eq 'PR'",
        "$top": PAGE_SIZE,
        "$skip": skip,
        "$format": "json",
    }
    last_err = None
    for attempt in range(MAX_RETRIES):
        try:
            resp = session.get(OPENFEMA_URL, params=params, timeout=60)
            if resp.status_code == 429:
                logger.warning("  Rate limited — sleeping 30s")
                time.sleep(30)
                resp = session.get(OPENFEMA_URL, params=params, timeout=60)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            last_err = e
        if attempt < MAX_RETRIES - 1:
            wait = RETRY_BACKOFF[attempt]
            logger.warning(f"  Attempt {attempt + 1} failed ({last_err}) — retrying in {wait}s")
            time.sleep(wait)
    logger.error(f"  All {MAX_RETRIES} attempts failed: {last_err}")
    return None


def _records_to_df(records):
    if not records:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)
    df = pd.DataFrame(records)
    rename_map = {src: dst for src, dst in zip(NFIP_COLUMNS, OUTPUT_COLUMNS) if src in df.columns}
    df = df.rename(columns=rename_map)
    for col in OUTPUT_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    return df[OUTPUT_COLUMNS]


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
    out_path = root / "data" / "staging" / "processed" / "pr_nfip_claims.csv"

    logger = setup_logging("download_nfip")
    logger.info("Starting NFIP claims download for Puerto Rico (OpenFEMA)...")

    if not force and _file_has_data(out_path):
        rows = len(pd.read_csv(out_path, dtype=str, low_memory=False))
        logger.info(f"  pr_nfip_claims.csv exists ({rows:,} rows) — skipping. Use --force to re-download.")
        return {"rows": rows, "path": str(out_path), "errors": []}

    session = _session()
    all_frames = []
    skip = 0
    total = 0
    errors = []

    while True:
        logger.info(f"  Fetching records {skip:,}–{skip + PAGE_SIZE:,}...")
        data = _fetch_page(session, skip, logger)
        if data is None:
            errors.append(f"Fetch failed at skip={skip}")
            break
        records = data.get("FimaNfipClaims", data.get("data", []))
        if not records:
            break
        df = _records_to_df(records)
        all_frames.append(df)
        total += len(df)
        logger.info(f"    Got {len(df)} records (total so far: {total:,})")
        if len(records) < PAGE_SIZE:
            break
        skip += PAGE_SIZE
        time.sleep(PAGE_SLEEP)

    session.close()

    if all_frames:
        combined = pd.concat(all_frames, ignore_index=True)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        combined.to_csv(out_path, index=False, encoding="utf-8")
        logger.info(f"  Written: pr_nfip_claims.csv ({len(combined):,} claim records)")
    else:
        pd.DataFrame(columns=OUTPUT_COLUMNS).to_csv(out_path, index=False, encoding="utf-8")
        logger.warning("  No NFIP records returned — wrote empty file")
        total = 0

    logger.info("=" * 60)
    logger.info("NFIP CLAIMS SUMMARY")
    logger.info("=" * 60)
    logger.info(f"  Total PR claim records: {total:,}")
    if errors:
        for e in errors:
            logger.warning(f"    {e}")

    paid_building = paid_contents = 0
    if all_frames:
        combined = pd.read_csv(out_path, dtype=str, low_memory=False)
        paid_building = pd.to_numeric(combined.get("paid_building", pd.Series()), errors="coerce").fillna(0).sum()
        paid_contents = pd.to_numeric(combined.get("paid_contents", pd.Series()), errors="coerce").fillna(0).sum()
        logger.info(f"  Total paid (building):  ${paid_building:,.0f}")
        logger.info(f"  Total paid (contents):  ${paid_contents:,.0f}")

    return {"rows": total, "path": str(out_path), "errors": errors}


def main():
    parser = argparse.ArgumentParser(description="Download NFIP claims for Puerto Rico")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    result = _run(force=args.force)
    print(f"\nNFIP complete: {result['rows']:,} records")
    return 1 if result["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
