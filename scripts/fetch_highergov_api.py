"""Fetch HigherGov API exports and write normalized CSVs into data/staging/expansion.

Reads API key from HIGHERGOV_API_KEY env var.
"""
from __future__ import annotations
import os
import sys
from pathlib import Path
import time

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests
import pandas as pd

from scripts.config import get_highergov_api_key

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = PROJECT_ROOT / "data" / "staging" / "expansion"
OUT_DIR.mkdir(parents=True, exist_ok=True)

API_BASE = "https://highergov.com/api-external"

# resources to fetch: mapping to output filenames and params
RESOURCES = {
    # include search_id and ordering values found inside PDFs to replicate the original exports
    "opportunity": ("highergov_municipal_awards.csv", {"page_size": 400, "search_id": "r7RyFxqYkkbkG3M2GyPg-", "source_type": "sled", "ordering": "-posted_date"}),
    "idv": ("highergov_idv_awards.csv", {"page_size": 2000, "search_id": "O1czhtUyFqdyKMpmMJNvm", "ordering": "-last_modified_date"}),
    "contract": ("highergov_prime_awards.csv", {"page_size": 20000, "search_id": "O1czhtUyFqdyKMpmMJNvm", "ordering": "-last_modified_date"}),
    "subcontract": ("highergov_sub_awards.csv", {"page_size": 800, "search_id": "O1czhtUyFqdyKMpmMJNvm", "ordering": "-last_modified_date"}),
}


def fetch_resource(resource: str, api_key: str, params: dict) -> pd.DataFrame | None:
    url = f"{API_BASE}/{resource}/"
    qs = dict(params)
    qs["api_key"] = api_key
    try:
        resp = requests.get(url, params=qs, timeout=30)
        resp.raise_for_status()
    except Exception as e:
        print(f"Failed to fetch {resource}: {e}")
        return None

    try:
        js = resp.json()
    except Exception as e:
        print(f"Non-JSON response for {resource}: {e}")
        return None

    # Attempt to find data list in common keys
    candidates = []
    if isinstance(js, list):
        candidates = js
    elif isinstance(js, dict):
        # common keys
        for k in ("results", "data", "items", "rows", "hits"):
            if k in js and isinstance(js[k], list):
                candidates = js[k]
                break
        # fallback: if dict has numeric-keyed dicts, try flattening
        if not candidates:
            # look for any list values
            for v in js.values():
                if isinstance(v, list):
                    candidates = v
                    break
    if not candidates:
        print(f"No list-like data found in {resource} response")
        return None

    # Normalize list of records
    try:
        df = pd.json_normalize(candidates)
    except Exception as e:
        print(f"json_normalize failed for {resource}: {e}")
        return None

    return df


def main():
    api_key = get_highergov_api_key()  # env -> .env -> None
    if not api_key:
        print("HIGHERGOV_API_KEY not set")
        return 2

    for resource, (out_name, params) in RESOURCES.items():
        print(f"Fetching {resource}...")
        df = fetch_resource(resource, api_key, params)
        if df is None:
            print(f"  Skipped {resource} (no data)")
            continue
        out_path = OUT_DIR / out_name
        try:
            df.to_csv(out_path, index=False, encoding="utf-8")
            print(f"  Wrote {out_path} ({len(df)} rows)")
        except Exception as e:
            print(f"  Failed to write CSV for {resource}: {e}")
        time.sleep(1)

    return 0


if __name__ == '__main__':
    sys.exit(main())
