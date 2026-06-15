"""
Download Puerto Rico power-sector time series from the U.S. Energy Information
Administration (EIA) API v2.

Series catalog is config-driven via registries/eia_series.yaml. The fetcher
iterates over the catalog, calls EIA API v2 for each series, and writes a
long-format CSV (one row per (series_id, period)) for downstream temporal
joins with PREPA contract and award data.

Output:
  data/staging/processed/pr_eia_power_sector.csv  — long format
  data/staging/raw/eia/<series_id>.json           — per-series raw API snapshots

Usage:
  python3 scripts/download_eia.py [--force] [--only <series_id> ...]

Requires:
  EIA_API_KEY — free, register at https://www.eia.gov/opendata/register.php
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

from scripts.config import PROCESSED_DIR, PROJECT_ROOT, get_eia_api_key, setup_logging

CATALOG_PATH = PROJECT_ROOT / "registries" / "eia_series.yaml"
OUTPUT_PATH = PROCESSED_DIR / "pr_eia_power_sector.csv"
RAW_DIR = PROJECT_ROOT / "data" / "staging" / "raw" / "eia"

PAGE_SIZE = 5000
PAGE_SLEEP = 0.4
MAX_RETRIES = 3
RETRY_BACKOFF = [5, 15, 30]
REQUEST_TIMEOUT = 60

OUTPUT_COLUMNS = [
    "series_id",
    "date",
    "value",
    "units",
    "frequency",
    "description",
    "route",
    "data_field",
    "raw_period",
    "source_date",
]


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update(
        {
            "User-Agent": "ContractSweeper/1.0 (PR power-sector research; contact via repo)",
            "Accept": "application/json",
        }
    )
    return s


def _load_catalog(path: Path = CATALOG_PATH) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"EIA series catalog not found: {path}")
    with path.open("r", encoding="utf-8") as f:
        catalog = yaml.safe_load(f)
    if not isinstance(catalog, dict) or "series" not in catalog:
        raise ValueError(f"{path}: missing top-level 'series' key")
    return catalog


def _build_url(base_url: str, route: str) -> str:
    return f"{base_url.rstrip('/')}/{route.strip('/')}/data/"


def _build_params(
    api_key: str, series: dict, default_start: str, offset: int = 0
) -> list[tuple[str, str]]:
    """
    EIA API v2 accepts repeated query-string params for `data[]` and `facets[key][]`.
    We build a list of (key, value) pairs and let requests serialize it correctly.
    """
    params: list[tuple[str, str]] = [
        ("api_key", api_key),
        ("frequency", str(series.get("frequency", "monthly"))),
        ("data[0]", str(series["data_field"])),
        ("start", str(series.get("start", default_start))),
        ("offset", str(offset)),
        ("length", str(PAGE_SIZE)),
        ("sort[0][column]", "period"),
        ("sort[0][direction]", "asc"),
    ]
    end = series.get("end")
    if end:
        params.append(("end", str(end)))
    facets = series.get("facets") or {}
    for facet_key, values in facets.items():
        if not isinstance(values, list):
            values = [values]
        for v in values:
            params.append((f"facets[{facet_key}][]", str(v)))
    return params


def _get_with_retry(session: requests.Session, url: str, params, logger) -> dict | None:
    for attempt in range(MAX_RETRIES):
        try:
            resp = session.get(url, params=params, timeout=REQUEST_TIMEOUT)
            if resp.status_code == 429:
                logger.warning("  Rate-limited (429) — sleeping 60s")
                time.sleep(60)
                continue
            if resp.status_code == 403:
                logger.error(f"  HTTP 403 — check API key / endpoint authorization for {url}")
                return None
            if 400 <= resp.status_code < 500:
                # Log a short body excerpt to aid debugging client errors.
                body = (resp.text or "")[:300]
                logger.warning(f"  HTTP {resp.status_code} for {url}: {body}")
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
                logger.error(f"  All {MAX_RETRIES} attempts failed for {url}: {exc}")
    return None


def _fetch_series(
    session, api_key: str, series: dict, base_url: str, default_start: str, logger
) -> list[dict]:
    """Fetch one catalog entry, paginating with offset/length. Returns raw data rows."""
    series_id = series["series_id"]
    url = _build_url(base_url, series["route"])

    rows: list[dict] = []
    offset = 0
    while True:
        params = _build_params(api_key, series, default_start, offset=offset)
        payload = _get_with_retry(session, url, params, logger)
        if payload is None:
            logger.warning(f"  [{series_id}] no payload at offset={offset} — stopping")
            break
        response = payload.get("response") or {}
        warnings = response.get("warnings") or []
        if warnings:
            logger.info(f"  [{series_id}] EIA warnings: {warnings}")

        data = response.get("data") or []
        if not data:
            break

        rows.extend(data)
        total_str = str(response.get("total") or "")
        try:
            total = int(total_str)
        except ValueError:
            total = len(rows)

        if len(rows) >= total or len(data) < PAGE_SIZE:
            break
        offset += PAGE_SIZE

    return rows


def _cache_raw(series_id: str, rows: list[dict], raw_dir: Path) -> None:
    raw_dir.mkdir(parents=True, exist_ok=True)
    path = raw_dir / f"{series_id}.json"
    path.write_text(json.dumps(rows, indent=2, sort_keys=True), encoding="utf-8")


def _normalize_period(raw_period: str, frequency: str) -> str:
    """Normalize EIA period strings to ISO YYYY-MM-DD anchored at period start."""
    raw = (raw_period or "").strip()
    if not raw:
        return ""
    try:
        if frequency == "annual":
            return f"{int(raw):04d}-01-01"
        if frequency == "monthly":
            # EIA returns "YYYY-MM" for monthly series
            year_str, _, month_str = raw.partition("-")
            return f"{int(year_str):04d}-{int(month_str or 1):02d}-01"
        if frequency == "quarterly":
            # EIA returns "YYYYQn"
            year_str, _, q = raw.partition("Q")
            quarter = int(q or 1)
            month = (quarter - 1) * 3 + 1
            return f"{int(year_str):04d}-{month:02d}-01"
        if frequency == "daily":
            return pd.to_datetime(raw, errors="coerce").strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        pass
    # Fallback: best-effort pandas parse
    parsed = pd.to_datetime(raw, errors="coerce")
    return "" if pd.isna(parsed) else parsed.strftime("%Y-%m-%d")


def _rows_to_dataframe(series: dict, raw_rows: list[dict], source_date: str) -> pd.DataFrame:
    series_id = series["series_id"]
    description = series.get("description", "")
    units = series.get("units", "")
    route = series["route"]
    data_field = series["data_field"]
    frequency = series.get("frequency", "monthly")

    out_rows = []
    for r in raw_rows:
        raw_period = str(r.get("period", "") or "")
        date_iso = _normalize_period(raw_period, frequency)
        raw_value = r.get(data_field)
        # EIA returns values as strings; coerce numerically but keep "" on failure.
        value = pd.to_numeric(raw_value, errors="coerce")
        value_str = "" if pd.isna(value) else f"{float(value):.6f}".rstrip("0").rstrip(".")
        # Prefer EIA's own units field for this row if present; otherwise fall back to YAML.
        row_units = r.get(f"{data_field}-units") or units
        out_rows.append(
            {
                "series_id": series_id,
                "date": date_iso,
                "value": value_str,
                "units": row_units,
                "frequency": frequency,
                "description": description,
                "route": route,
                "data_field": data_field,
                "raw_period": raw_period,
                "source_date": source_date,
            }
        )

    if not out_rows:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)
    return pd.DataFrame(out_rows, columns=OUTPUT_COLUMNS)


def run(root: Path = None, force: bool = False, only: list[str] | None = None) -> dict:
    if root is None:
        root = PROJECT_ROOT
    root = Path(root)

    logger = setup_logging("download_eia")
    catalog = _load_catalog()
    base_url = str(catalog.get("base_url", "https://api.eia.gov/v2"))
    default_start = str(catalog.get("default_start", "2010-01"))
    series_list = catalog.get("series") or []

    if only:
        keep = {s.strip() for s in only if s and s.strip()}
        before = len(series_list)
        series_list = [s for s in series_list if s.get("series_id") in keep]
        logger.info(f"  --only filter: {len(series_list)}/{before} series selected")

    if not series_list:
        logger.error("  No series to fetch — check eia_series.yaml or --only filter")
        return {"status": "EMPTY", "rows": 0, "series_count": 0, "output_path": str(OUTPUT_PATH)}

    api_key = get_eia_api_key()  # raises with a clear message if missing

    output_dir = root / "data" / "staging" / "processed"
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / OUTPUT_PATH.name
    raw_dir = root / "data" / "staging" / "raw" / "eia"

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
            logger.info(f"    {len(df):,} rows")
    finally:
        session.close()

    if frames:
        combined = pd.concat(frames, ignore_index=True)
    else:
        combined = pd.DataFrame(columns=OUTPUT_COLUMNS)

    combined = combined.sort_values(["series_id", "date"]).reset_index(drop=True)
    combined.to_csv(out_path, index=False, encoding="utf-8")

    populated_series = sum(1 for _, n in per_series_stats if n > 0)
    total_rows = len(combined)

    logger.info("=" * 60)
    logger.info("EIA PR POWER-SECTOR SUMMARY")
    logger.info("=" * 60)
    logger.info(f"  Series fetched:       {len(per_series_stats)}")
    logger.info(f"  Series with data:     {populated_series}")
    logger.info(f"  Total long-form rows: {total_rows:,}")
    logger.info(f"  Output:               {out_path}")
    if per_series_stats:
        logger.info("  Per-series row counts:")
        for sid, n in per_series_stats:
            logger.info(f"    {sid:<40s} {n:>6,}")

    status = "OK" if populated_series > 0 else "EMPTY"
    return {
        "status": status,
        "rows": total_rows,
        "series_count": len(per_series_stats),
        "series_populated": populated_series,
        "output_path": str(out_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Download PR power-sector time series from EIA API v2",
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
        # Most commonly: missing EIA_API_KEY
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    except Exception as e:
        print(f"FATAL: {e}", file=sys.stderr)
        return 1

    print(
        f"\nEIA complete: {result.get('rows', 0):,} rows across "
        f"{result.get('series_populated', 0)}/{result.get('series_count', 0)} series "
        f"(status={result.get('status')})."
    )
    return 0 if result["status"] in ("OK", "CACHED") else 1


if __name__ == "__main__":
    sys.exit(main())
