"""
Download Puerto Rico macroeconomic time series from FRED (Federal Reserve
Economic Data, St. Louis Fed).

Series catalog is config-driven via registries/fred_series.yaml. The fetcher
iterates over the catalog, calls FRED API v1 for each series, and writes a
long-format CSV (one row per (series_id, observation date)) for downstream
temporal joins with PR contract/award data.

Output:
  data/staging/processed/pr_fred_timeseries.csv  — long format
  data/staging/raw/fred/<series_id>.json         — per-series raw API snapshots

Usage:
  python3 scripts/download_fred.py [--force] [--only <series_id> ...]

Requires:
  FRED_API_KEY — free, register at https://fred.stlouisfed.org/docs/api/api_key.html
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import requests
import yaml

from scripts.config import PROCESSED_DIR, PROJECT_ROOT, get_fred_api_key, setup_logging

CATALOG_PATH = PROJECT_ROOT / "registries" / "fred_series.yaml"
OUTPUT_PATH = PROCESSED_DIR / "pr_fred_timeseries.csv"
RAW_DIR = PROJECT_ROOT / "data" / "staging" / "raw" / "fred"

PAGE_SLEEP = 0.3
MAX_RETRIES = 3
RETRY_BACKOFF = [5, 15, 30]
REQUEST_TIMEOUT = 60
# FRED's default observation limit is 100,000 per request — more than enough
# for any single PR series, so no pagination is needed.

OUTPUT_COLUMNS = [
    "series_id",
    "date",
    "value",
    "units",
    "frequency",
    "description",
    "raw_date",
    "source_date",
]


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update(
        {
            "User-Agent": "ContractSweeper/1.0 (PR macro research; contact via repo)",
            "Accept": "application/json",
        }
    )
    return s


def _load_catalog(path: Path = CATALOG_PATH) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"FRED series catalog not found: {path}")
    with path.open("r", encoding="utf-8") as f:
        catalog = yaml.safe_load(f)
    if not isinstance(catalog, dict) or "series" not in catalog:
        raise ValueError(f"{path}: missing top-level 'series' key")
    return catalog


def _get_with_retry(session: requests.Session, url: str, params: dict, logger) -> dict | None:
    for attempt in range(MAX_RETRIES):
        try:
            resp = session.get(url, params=params, timeout=REQUEST_TIMEOUT)
            if resp.status_code == 429:
                logger.warning("  Rate-limited (429) — sleeping 60s")
                time.sleep(60)
                continue
            if resp.status_code == 400:
                # FRED returns 400 for unknown series IDs. Log + skip.
                body = (resp.text or "")[:200]
                logger.warning(f"  HTTP 400 (likely unknown series): {body}")
                return None
            if resp.status_code == 403:
                logger.error("  HTTP 403 — check FRED_API_KEY")
                return None
            resp.raise_for_status()
            time.sleep(PAGE_SLEEP)
            return resp.json()
        except requests.RequestException as exc:
            if attempt < MAX_RETRIES - 1:
                wait = RETRY_BACKOFF[attempt]
                logger.warning(f"  Attempt {attempt + 1} failed ({exc}) — retrying in {wait}s")
                time.sleep(wait)
            else:
                logger.error(f"  All {MAX_RETRIES} attempts failed: {exc}")
    return None


def _fetch_series(
    session, api_key: str, series: dict, base_url: str, default_start: str, logger
) -> list[dict]:
    series_id = series["series_id"]
    url = f"{base_url.rstrip('/')}/series/observations"
    params = {
        "series_id": series_id,
        "api_key": api_key,
        "file_type": "json",
        "observation_start": str(series.get("start", default_start)),
        "sort_order": "asc",
    }
    end = series.get("end")
    if end:
        params["observation_end"] = str(end)
    payload = _get_with_retry(session, url, params, logger)
    if payload is None:
        return []
    obs = payload.get("observations") or []
    return obs


def _cache_raw(series_id: str, rows: list[dict], raw_dir: Path) -> None:
    raw_dir.mkdir(parents=True, exist_ok=True)
    path = raw_dir / f"{series_id}.json"
    path.write_text(json.dumps(rows, indent=2, sort_keys=True), encoding="utf-8")


def _rows_to_dataframe(series: dict, raw_rows: list[dict], source_date: str) -> pd.DataFrame:
    series_id = series["series_id"]
    description = series.get("description", "")
    units = series.get("units", "")
    frequency = series.get("frequency", "monthly")

    out_rows = []
    for r in raw_rows:
        raw_date = str(r.get("date", "") or "")
        # FRED uses "." for missing values.
        raw_value = r.get("value")
        if raw_value in (None, "", "."):
            value_str = ""
        else:
            num = pd.to_numeric(raw_value, errors="coerce")
            value_str = "" if pd.isna(num) else f"{float(num):.6f}".rstrip("0").rstrip(".")
        out_rows.append(
            {
                "series_id": series_id,
                "date": raw_date,  # FRED already returns YYYY-MM-DD
                "value": value_str,
                "units": units,
                "frequency": frequency,
                "description": description,
                "raw_date": raw_date,
                "source_date": source_date,
            }
        )

    if not out_rows:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)
    return pd.DataFrame(out_rows, columns=OUTPUT_COLUMNS)


def run(root: Path | None = None, force: bool = False, only: list[str] | None = None) -> dict:
    if root is None:
        root = PROJECT_ROOT
    root = Path(root)

    logger = setup_logging("download_fred")
    catalog = _load_catalog()
    base_url = str(catalog.get("base_url", "https://api.stlouisfed.org/fred"))
    default_start = str(catalog.get("default_start", "1990-01-01"))
    series_list = catalog.get("series") or []

    if only:
        keep = {s.strip() for s in only if s and s.strip()}
        before = len(series_list)
        series_list = [s for s in series_list if s.get("series_id") in keep]
        logger.info(f"  --only filter: {len(series_list)}/{before} series selected")

    if not series_list:
        logger.error("  No series to fetch — check fred_series.yaml or --only filter")
        return {"status": "EMPTY", "rows": 0, "series_count": 0, "output_path": str(OUTPUT_PATH)}

    api_key = get_fred_api_key()  # raises with a clear message if missing

    output_dir = root / "data" / "staging" / "processed"
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / OUTPUT_PATH.name
    raw_dir = root / "data" / "staging" / "raw" / "fred"

    if not force and out_path.exists():
        logger.info(f"  Cached — {out_path.name} exists. Use --force to refresh.")
        try:
            df_cached = pd.read_csv(out_path, dtype=str, low_memory=False)
            return {
                "status": "CACHED",
                "rows": len(df_cached),
                "series_count": df_cached["series_id"].nunique()
                if "series_id" in df_cached.columns
                else 0,
                "output_path": str(out_path),
            }
        except Exception as e:
            logger.warning(f"  Cache unreadable ({e}) — refetching")

    session = _session()
    source_date = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    frames: list[pd.DataFrame] = []
    per_series_stats: list[tuple[str, int]] = []

    try:
        for idx, series in enumerate(series_list, start=1):
            series_id = series.get("series_id") or f"_unnamed_{idx}"
            logger.info(f"  [{idx}/{len(series_list)}] {series_id}")
            try:
                raw_rows = _fetch_series(session, api_key, series, base_url, default_start, logger)
            except Exception as e:
                logger.error(f"  [{series_id}] fetch failed: {e}")
                raw_rows = []
            _cache_raw(series_id, raw_rows, raw_dir)
            df = _rows_to_dataframe(series, raw_rows, source_date)
            frames.append(df)
            per_series_stats.append((series_id, len(df)))
            logger.info(f"    {len(df):,} observations")
    finally:
        session.close()

    if frames:
        combined = pd.concat(frames, ignore_index=True)
    else:
        combined = pd.DataFrame(columns=OUTPUT_COLUMNS)

    combined = combined.sort_values(["series_id", "date"]).reset_index(drop=True)
    combined.to_csv(out_path, index=False, encoding="utf-8")

    populated = sum(1 for _, n in per_series_stats if n > 0)
    total_rows = len(combined)

    logger.info("=" * 60)
    logger.info("FRED PR MACRO SUMMARY")
    logger.info("=" * 60)
    logger.info(f"  Series fetched:       {len(per_series_stats)}")
    logger.info(f"  Series with data:     {populated}")
    logger.info(f"  Total long-form rows: {total_rows:,}")
    logger.info(f"  Output:               {out_path}")
    if per_series_stats:
        logger.info("  Per-series observation counts:")
        for sid, n in per_series_stats:
            logger.info(f"    {sid:<25s} {n:>6,}")

    status = "OK" if populated > 0 else "EMPTY"
    return {
        "status": status,
        "rows": total_rows,
        "series_count": len(per_series_stats),
        "series_populated": populated,
        "output_path": str(out_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Download PR macroeconomic time series from FRED API v1",
    )
    parser.add_argument(
        "--force", action="store_true", help="Re-fetch even if the output CSV already exists"
    )
    parser.add_argument(
        "--only",
        action="append",
        default=None,
        help="Restrict to a specific series_id (repeatable)",
    )
    args = parser.parse_args()

    try:
        result = run(force=args.force, only=args.only)
    except RuntimeError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    except Exception as e:
        print(f"FATAL: {e}", file=sys.stderr)
        return 1

    print(
        f"\nFRED complete: {result.get('rows', 0):,} rows across "
        f"{result.get('series_populated', 0)}/{result.get('series_count', 0)} series "
        f"(status={result.get('status')})."
    )
    return 0 if result["status"] in ("OK", "CACHED") else 1


if __name__ == "__main__":
    sys.exit(main())
