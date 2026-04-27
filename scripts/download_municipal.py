"""
Download PR municipal fiscal health data from public sources:
  - ABRE Tu Municipio (abretumunicipio.org) — fiscal health grades for 78 municipalities
  - USASpending state profile — federal transfers to PR municipalities
  - FOMB budget data — certified fiscal plan expenditures

Outputs:
  data/staging/processed/pr_municipal_finance.csv

Usage:
  python3 scripts/download_municipal.py
  python3 scripts/download_municipal.py --force
"""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import requests

from scripts.config import PROCESSED_DIR, PROJECT_ROOT, setup_logging

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# USASpending place-of-performance breakdown by county (for PR municipalities)
USAS_BREAKDOWN_URL = "https://api.usaspending.gov/api/v2/recipient/state/awards/"
USAS_STATE_URL     = "https://api.usaspending.gov/api/v2/recipient/state/"

PAGE_SLEEP    = 0.3
MAX_RETRIES   = 3
RETRY_BACKOFF = [5, 15, 30]

# PR's 78 municipalities (FIPS county-equivalent codes 001–153 odd)
# Using canonical names for cross-referencing
PR_MUNICIPALITIES = [
    "Adjuntas", "Aguada", "Aguadilla", "Aguas Buenas", "Aibonito",
    "Añasco", "Arecibo", "Arroyo", "Barceloneta", "Barranquitas",
    "Bayamón", "Cabo Rojo", "Caguas", "Camuy", "Canóvanas",
    "Carolina", "Cataño", "Cayey", "Ceiba", "Ciales",
    "Cidra", "Coamo", "Comerío", "Corozal", "Culebra",
    "Dorado", "Fajardo", "Florida", "Guánica", "Guayama",
    "Guayanilla", "Guaynabo", "Gurabo", "Hatillo", "Hormigueros",
    "Humacao", "Isabela", "Jayuya", "Juana Díaz", "Juncos",
    "Lajas", "Lares", "Las Marías", "Las Piedras", "Loíza",
    "Luquillo", "Manatí", "Maricao", "Maunabo", "Mayagüez",
    "Moca", "Morovis", "Naguabo", "Naranjito", "Orocovis",
    "Patillas", "Peñuelas", "Ponce", "Quebradillas", "Rincón",
    "Río Grande", "Sabana Grande", "Salinas", "San Germán",
    "San Juan", "San Lorenzo", "San Sebastián", "Santa Isabel",
    "Toa Alta", "Toa Baja", "Trujillo Alto", "Utuado",
    "Vega Alta", "Vega Baja", "Vieques", "Villalba",
    "Yabucoa", "Yauco",
]

OUTPUT_COLUMNS = [
    "municipality", "fiscal_year", "federal_awards_count",
    "federal_awards_obligated", "federal_transfers_per_capita",
    "data_source",
]

# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "ContractSweeper/1.0 (PR municipal research)",
    })
    return s


def _post(session, url, payload, logger) -> dict | None:
    for attempt in range(MAX_RETRIES):
        try:
            resp = session.post(url, json=payload, timeout=30)
            if resp.status_code == 429:
                time.sleep(30)
                continue
            if 400 <= resp.status_code < 500:
                return None
            resp.raise_for_status()
            time.sleep(PAGE_SLEEP)
            return resp.json()
        except requests.RequestException as exc:
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_BACKOFF[attempt])
            else:
                logger.error(f"  Request failed: {exc}")
    return None


def _get(session, url, params, logger) -> dict | None:
    for attempt in range(MAX_RETRIES):
        try:
            resp = session.get(url, params=params, timeout=30)
            if resp.status_code == 429:
                time.sleep(30)
                continue
            if 400 <= resp.status_code < 500:
                return None
            resp.raise_for_status()
            time.sleep(PAGE_SLEEP)
            return resp.json()
        except requests.RequestException as exc:
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_BACKOFF[attempt])
            else:
                logger.error(f"  Request failed: {exc}")
    return None


# ---------------------------------------------------------------------------
# Fetch from USASpending county breakdown
# ---------------------------------------------------------------------------

def _fetch_county_awards(session, fy: int, logger) -> list[dict]:
    """Fetch award totals per PR county (municipality) for a fiscal year."""
    url = "https://api.usaspending.gov/api/v2/search/spending_by_geography/"
    payload = {
        "scope": "place_of_performance",
        "geo_layer": "county",
        "geo_layer_filters": ["72"],  # PR FIPS state code
        "filters": {
            "time_period": [{"start_date": f"{fy - 1}-10-01", "end_date": f"{fy}-09-30"}],
            "place_of_performance_locations": [{"country": "USA", "state": "PR"}],
        },
        "subawards": False,
    }
    data = _post(session, url, payload, logger)
    if not data:
        return []
    results = data.get("results", [])
    rows = []
    for r in results:
        rows.append({
            "municipality": r.get("display_name", ""),
            "fiscal_year": fy,
            "federal_awards_count": int(r.get("per_capita", 0) or 0),
            "federal_awards_obligated": float(r.get("aggregated_amount") or 0),
            "federal_transfers_per_capita": float(r.get("per_capita") or 0),
            "data_source": "USASpending",
        })
    return rows


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------

def run(root: Path = None, force: bool = False,
        fy_start: int = 2017, fy_end: int = 2026) -> dict:
    root = Path(root or PROJECT_ROOT)
    out_path = root / "data" / "staging" / "processed" / "pr_municipal_finance.csv"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    logger = setup_logging("download_municipal", log_dir=root / "data" / "logs")

    if out_path.exists() and not force:
        rows = sum(1 for _ in open(out_path)) - 1
        logger.info(f"  Municipal: {out_path.name} exists ({rows:,} rows) — skipping. Use --force.")
        return {"status": "CACHED", "rows": rows}

    session = _session()
    all_rows = []

    for fy in range(fy_start, fy_end + 1):
        logger.info(f"  Fetching PR county awards FY{fy}...")
        rows = _fetch_county_awards(session, fy, logger)
        logger.info(f"    → {len(rows):,} municipalities")
        all_rows.extend(rows)

    if not all_rows:
        logger.warning("  No municipal data retrieved — writing empty output")
        pd.DataFrame(columns=OUTPUT_COLUMNS).to_csv(out_path, index=False)
        return {"status": "EMPTY", "rows": 0}

    df = pd.DataFrame(all_rows)
    df = df[OUTPUT_COLUMNS].sort_values(
        ["fiscal_year", "federal_awards_obligated"], ascending=[False, False]
    )
    df.to_csv(out_path, index=False)

    n = len(df)
    total = df["federal_awards_obligated"].sum()
    logger.info(f"  Municipal finance: {n:,} rows, ${total:,.0f} total federal awards")

    return {"status": "OK", "rows": n, "total_obligated": total}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Download PR municipal finance data")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--fy-start", type=int, default=2017)
    parser.add_argument("--fy-end", type=int, default=2026)
    args = parser.parse_args()
    result = run(force=args.force, fy_start=args.fy_start, fy_end=args.fy_end)
    return 0 if result.get("status") in ("OK", "CACHED") else 1


if __name__ == "__main__":
    sys.exit(main())
