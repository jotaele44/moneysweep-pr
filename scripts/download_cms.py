"""
Download CMS (Centers for Medicare & Medicaid Services) financial data for PR.

Two datasets:

1. Open Payments (Sunshine Act) — payments FROM pharmaceutical/device
   manufacturers TO Puerto Rico healthcare providers. Covers general,
   research, and ownership-interest payments. 2013-present.
   Source: openpaymentsdata.cms.gov

2. Medicare Part B Provider Payments — total Medicare reimbursements
   received BY PR physicians, hospitals, and other suppliers.
   Source: data.cms.gov (Socrata)

Output:
  data/staging/raw/cms/pr_open_payments.csv
  data/staging/raw/cms/pr_medicare_providers.csv
  data/staging/processed/pr_cms_open_payments.csv
  data/staging/processed/pr_cms_medicare_providers.csv

Usage:
  python3 scripts/download_cms.py
  python3 scripts/download_cms.py --skip-open-payments
  python3 scripts/download_cms.py --skip-medicare
  python3 scripts/download_cms.py --force
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

OPEN_PAYMENTS_BASE  = "https://openpaymentsdata.cms.gov/api/1"
CMS_DATA_BASE       = "https://data.cms.gov/data-api/v1/dataset"

PAGE_SIZE    = 5000
PAGE_SLEEP   = 0.4
MAX_RETRIES  = 3
RETRY_BACKOFF = [5, 15, 30]

# Open Payments catalog tag to filter for the General Payments dataset
OPEN_PAYMENTS_PROGRAM = "Open Payments"

# CMS Medicare Part B dataset UUIDs (stable across CMS data releases)
# "Medicare Physician & Other Practitioners - by Provider"
# Most recent available years — CMS adds a new year each spring
MEDICARE_DATASET_IDS = [
    "9767cb68-8ea9-4f0b-8179-9431abc89f11",  # 2022
    "eed17e25-0c44-4fef-824c-e6be99804e91",  # 2021
]

OPEN_PAYMENTS_COLUMNS = [
    "payment_year",
    "payer_name",
    "payer_state",
    "recipient_type",
    "covered_recipient_npi",
    "recipient_name",
    "recipient_specialty",
    "recipient_city",
    "recipient_state",
    "total_amount",
    "payment_nature",
    "payment_form",
    "product_type",
    "product_category",
    "product_name",
    "dispute_status",
]

MEDICARE_COLUMNS = [
    "npi",
    "provider_last_name",
    "provider_first_name",
    "provider_credentials",
    "provider_gender",
    "provider_entity_type",
    "provider_city",
    "provider_state",
    "provider_zip",
    "provider_type",
    "total_submitted_charges",
    "total_medicare_allowed",
    "total_medicare_payment",
    "total_medicare_standardized",
    "total_services",
    "total_unique_benes",
    "drug_suppress_indicator",
]


# ---------------------------------------------------------------------------
# Network helpers
# ---------------------------------------------------------------------------

def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": "ContractSweeper/1.0 (PR healthcare spending research)",
        "Accept":     "application/json",
    })
    return s


def _get(session: requests.Session, url: str, params: dict, logger,
         method: str = "GET", json_body: dict = None) -> dict | list | None:
    for attempt in range(MAX_RETRIES):
        try:
            if method == "POST":
                resp = session.post(url, json=json_body, timeout=60)
            else:
                resp = session.get(url, params=params, timeout=60)
            if resp.status_code == 429:
                logger.warning("  Rate limited — sleeping 60s")
                time.sleep(60)
                continue
            if resp.status_code == 404:
                return None
            if 400 <= resp.status_code < 500:
                logger.warning(f"  HTTP {resp.status_code}: {resp.text[:200]}")
                return None
            resp.raise_for_status()
            time.sleep(PAGE_SLEEP)
            return resp.json()
        except requests.RequestException as exc:
            if attempt < MAX_RETRIES - 1:
                wait = RETRY_BACKOFF[attempt]
                logger.warning(f"  Attempt {attempt + 1} failed ({exc}) — retry in {wait}s")
                time.sleep(wait)
            else:
                logger.error(f"  All {MAX_RETRIES} attempts failed: {exc}")
    return None


# ---------------------------------------------------------------------------
# Open Payments
# ---------------------------------------------------------------------------

def _discover_open_payments_datasets(session: requests.Session, logger) -> list[str]:
    """Return resource UUIDs for all Open Payments 'General' payment datasets."""
    url  = f"{OPEN_PAYMENTS_BASE}/metastore/schemas/dataset/items"
    data = _get(session, url, {"limit": 500, "offset": 0}, logger)
    if not data:
        return []

    uuids = []
    for item in data:
        if not isinstance(item, dict):
            continue
        title = (item.get("title") or "").lower()
        tags  = [t.get("data", "").lower() for t in (item.get("keyword") or [])]
        # Target: general payment datasets (not research/ownership)
        if "general payment" in title and "open payments" in tags:
            identifier = item.get("identifier") or ""
            if identifier:
                uuids.append(identifier)

    logger.info(f"  Discovered {len(uuids)} Open Payments General Payment datasets")
    return uuids


def _fetch_open_payments_dataset(session: requests.Session, uuid: str, logger) -> list[dict]:
    """Fetch all PR rows from one Open Payments dataset resource."""
    url     = f"{OPEN_PAYMENTS_BASE}/datastore/query/{uuid}/0"
    offset  = 0
    records = []

    while True:
        params = {
            "conditions[0][property]": "Recipient_State",
            "conditions[0][value]":    "PR",
            "conditions[0][operator]": "=",
            "limit":  PAGE_SIZE,
            "offset": offset,
        }
        data = _get(session, url, params, logger)
        if not data:
            break
        batch = data.get("results") or data.get("data") or []
        if not batch:
            break
        records.extend(batch)
        total = data.get("count") or data.get("total") or 0
        if offset == 0 and total:
            logger.info(f"    Dataset {uuid[:8]}…: {total:,} PR records")
        if offset + PAGE_SIZE >= total:
            break
        offset += PAGE_SIZE

    return records


def _normalize_open_payments(records: list[dict]) -> pd.DataFrame:
    if not records:
        return pd.DataFrame(columns=OPEN_PAYMENTS_COLUMNS)

    df = pd.DataFrame(records)
    # Normalize column names: lowercase, replace spaces
    df.columns = [c.lower().replace(" ", "_") for c in df.columns]

    col_map = {
        "program_year":                     "payment_year",
        "applicable_manufacturer_or_applicable_gpo_making_payment_name": "payer_name",
        "applicable_manufacturer_or_applicable_gpo_making_payment_state": "payer_state",
        "covered_recipient_type":           "recipient_type",
        "covered_recipient_npi":            "covered_recipient_npi",
        "covered_recipient_last_name":      "_last",
        "covered_recipient_first_name":     "_first",
        "covered_recipient_primary_type_1": "recipient_specialty",
        "recipient_city":                   "recipient_city",
        "recipient_state_code":             "recipient_state",
        "total_amount_of_payment_usdollars": "total_amount",
        "nature_of_payment_or_transfer_of_value": "payment_nature",
        "form_of_payment_or_transfer_of_value":   "payment_form",
        "product_type_1":                   "product_type",
        "name_of_drug_or_biological_or_device_or_medical_supply_1": "product_name",
        "dispute_status_for_publication":   "dispute_status",
        "indicate_drug_or_biological_or_device_or_medical_supply_1": "product_category",
    }
    df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})

    # Combine name fields if present
    if "_last" in df.columns or "_first" in df.columns:
        last  = df.get("_last",  pd.Series([""] * len(df)))
        first = df.get("_first", pd.Series([""] * len(df)))
        df["recipient_name"] = (first.fillna("") + " " + last.fillna("")).str.strip()
        df = df.drop(columns=["_last", "_first"], errors="ignore")

    for col in OPEN_PAYMENTS_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    return df[OPEN_PAYMENTS_COLUMNS]


def download_open_payments(session: requests.Session, raw_path: Path, logger,
                           force: bool) -> pd.DataFrame:
    if not force and raw_path.exists():
        logger.info("  Open Payments raw file exists — loading cached")
        return pd.read_csv(raw_path, dtype=str, low_memory=False)

    logger.info("Downloading CMS Open Payments for Puerto Rico...")
    uuids = _discover_open_payments_datasets(session, logger)

    if not uuids:
        logger.warning("  No Open Payments datasets discovered — trying fallback UUID list")
        # Known stable identifiers for recent program years
        uuids = [
            "3f219b86-adb3-4a9f-a289-db7b16f76659",  # 2022 General
            "7c4ff21d-b57f-4e5f-9a78-81fdcab6e748",  # 2021 General
            "a3f9d73b-e5f7-4e4c-9b17-2e4d3a2e1f5a",  # 2020 General
        ]

    all_records = []
    for uuid in uuids:
        recs = _fetch_open_payments_dataset(session, uuid, logger)
        all_records.extend(recs)
        logger.info(f"  Running total: {len(all_records):,} records")

    df = _normalize_open_payments(all_records)
    df.to_csv(raw_path, index=False, encoding="utf-8")
    return df


# ---------------------------------------------------------------------------
# Medicare Part B Provider Payments
# ---------------------------------------------------------------------------

def _fetch_medicare_dataset(session: requests.Session, dataset_id: str,
                             logger) -> list[dict]:
    """Fetch PR rows from one CMS Medicare Part B dataset."""
    url     = f"{CMS_DATA_BASE}/{dataset_id}/data"
    offset  = 0
    records = []

    while True:
        params = {
            "filter[Rndrng_Prvdr_State_Abrvtn]": "PR",
            "size":   PAGE_SIZE,
            "offset": offset,
        }
        data = _get(session, url, params, logger)
        if not data:
            break
        # CMS data API returns a list directly
        batch = data if isinstance(data, list) else (data.get("data") or [])
        if not batch:
            break
        records.extend(batch)
        if len(batch) < PAGE_SIZE:
            break
        offset += PAGE_SIZE

    return records


def _normalize_medicare(records: list[dict]) -> pd.DataFrame:
    if not records:
        return pd.DataFrame(columns=MEDICARE_COLUMNS)

    df = pd.DataFrame(records)
    df.columns = [c.lower() for c in df.columns]

    col_map = {
        "rndrng_npi":                  "npi",
        "rndrng_prvdr_last_org_name":  "provider_last_name",
        "rndrng_prvdr_first_name":     "provider_first_name",
        "rndrng_prvdr_crdntls":        "provider_credentials",
        "rndrng_prvdr_gndr":           "provider_gender",
        "rndrng_prvdr_ent_cd":         "provider_entity_type",
        "rndrng_prvdr_city":           "provider_city",
        "rndrng_prvdr_state_abrvtn":   "provider_state",
        "rndrng_prvdr_zip5":           "provider_zip",
        "rndrng_prvdr_type":           "provider_type",
        "tot_sbmtd_chrgs":             "total_submitted_charges",
        "tot_mdcr_alowd_amt":          "total_medicare_allowed",
        "tot_mdcr_pymt_amt":           "total_medicare_payment",
        "tot_mdcr_stdzd_amt":          "total_medicare_standardized",
        "tot_srvcs":                   "total_services",
        "tot_benes":                   "total_unique_benes",
        "drug_suprsr_ind":             "drug_suppress_indicator",
    }
    df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})
    for col in MEDICARE_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    return df[MEDICARE_COLUMNS]


def download_medicare(session: requests.Session, raw_path: Path, logger,
                      force: bool) -> pd.DataFrame:
    if not force and raw_path.exists():
        logger.info("  Medicare raw file exists — loading cached")
        return pd.read_csv(raw_path, dtype=str, low_memory=False)

    logger.info("Downloading CMS Medicare Part B provider payments for PR...")
    all_records = []

    for dataset_id in MEDICARE_DATASET_IDS:
        logger.info(f"  Dataset {dataset_id[:8]}…")
        recs = _fetch_medicare_dataset(session, dataset_id, logger)
        logger.info(f"  → {len(recs):,} PR provider rows")
        all_records.extend(recs)

    df = _normalize_medicare(all_records)

    # Aggregate by NPI across years: sum payments, keep latest profile
    if not df.empty and "npi" in df.columns:
        for col in ["total_submitted_charges", "total_medicare_allowed",
                    "total_medicare_payment", "total_services", "total_unique_benes"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        num_cols = ["total_submitted_charges", "total_medicare_allowed",
                    "total_medicare_payment", "total_services", "total_unique_benes"]
        str_cols = [c for c in MEDICARE_COLUMNS if c not in num_cols and c != "npi"]
        agg = {c: "sum" for c in num_cols if c in df.columns}
        agg.update({c: "first" for c in str_cols if c in df.columns})
        df = df.groupby("npi", as_index=False).agg(agg)

    df.to_csv(raw_path, index=False, encoding="utf-8")
    return df


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run(root: Path = None, skip_open_payments: bool = False,
        skip_medicare: bool = False, force: bool = False) -> dict:
    if root is None:
        root = PROJECT_ROOT

    root    = Path(root)
    raw_dir = root / "data" / "staging" / "raw" / "cms"
    out_dir = root / "data" / "staging" / "processed"
    raw_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)

    logger  = setup_logging("download_cms")
    session = _session()
    result  = {"status": "OK"}

    # Open Payments
    op_out_path  = out_dir / "pr_cms_open_payments.csv"
    op_raw_path  = raw_dir / "pr_open_payments.csv"
    if skip_open_payments:
        logger.info("Open Payments: SKIPPED (--skip-open-payments)")
        result["open_payments_rows"] = 0
    else:
        df_op = download_open_payments(session, op_raw_path, logger, force)
        df_op.to_csv(op_out_path, index=False, encoding="utf-8")
        total_op = pd.to_numeric(df_op.get("total_amount", pd.Series(dtype=float)),
                                 errors="coerce").sum()
        logger.info(f"  Open Payments: {len(df_op):,} rows, ${total_op:,.0f} total payments to PR providers")
        result["open_payments_rows"] = len(df_op)
        result["open_payments_path"] = str(op_out_path)

    # Medicare Part B
    med_out_path = out_dir / "pr_cms_medicare_providers.csv"
    med_raw_path = raw_dir / "pr_medicare_providers.csv"
    if skip_medicare:
        logger.info("Medicare Part B: SKIPPED (--skip-medicare)")
        result["medicare_rows"] = 0
    else:
        df_med = download_medicare(session, med_raw_path, logger, force)
        df_med.to_csv(med_out_path, index=False, encoding="utf-8")
        total_med = pd.to_numeric(df_med.get("total_medicare_payment", pd.Series(dtype=float)),
                                  errors="coerce").sum()
        logger.info(f"  Medicare Part B: {len(df_med):,} providers, ${total_med:,.0f} total payments")
        result["medicare_rows"] = len(df_med)
        result["medicare_path"] = str(med_out_path)

        if not df_med.empty:
            logger.info(f"\n  Top 10 PR Medicare providers by total payment:")
            df_top = df_med.copy()
            df_top["_pay"] = pd.to_numeric(df_top.get("total_medicare_payment", ""),
                                           errors="coerce").fillna(0)
            df_top = df_top.sort_values("_pay", ascending=False).head(10)
            for _, row in df_top.iterrows():
                name = (str(row.get("provider_last_name", "")) + ", " +
                        str(row.get("provider_first_name", ""))).strip(", ")
                ptype = str(row.get("provider_type", ""))[:30]
                pay   = row["_pay"]
                logger.info(f"    {name[:45]:<45}  ${pay:>12,.0f}  [{ptype}]")

    session.close()

    logger.info("=" * 60)
    logger.info("CMS DOWNLOAD SUMMARY")
    logger.info("=" * 60)
    logger.info(f"  Open Payments rows:    {result.get('open_payments_rows', 0):,}")
    logger.info(f"  Medicare provider rows:{result.get('medicare_rows', 0):,}")

    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Download CMS Open Payments and Medicare data for PR")
    parser.add_argument("--skip-open-payments", action="store_true")
    parser.add_argument("--skip-medicare",       action="store_true")
    parser.add_argument("--force", action="store_true", help="Re-download even if cached")
    args = parser.parse_args()
    result = run(skip_open_payments=args.skip_open_payments,
                 skip_medicare=args.skip_medicare, force=args.force)
    total = result.get("open_payments_rows", 0) + result.get("medicare_rows", 0)
    print(f"\nCMS download complete. {total:,} total rows.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
