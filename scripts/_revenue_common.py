"""
Shared dropzone-reader helpers for infrastructure REVENUE (income) producers.

moneysweep-pr historically tracks public-money *outflows* (contracts, grants,
disbursements). The revenue producers add the *income* side: what the public pays
to use infrastructure (tolls, transit fares, water/power rates, port/airport fees).

These figures are AGGREGATE / published — sourced from audited financial statements,
MSRB EMMA continuing-disclosure filings, and agency budgets. They are NOT individual
payment records (those are private and unobtainable). The operator drops exported
CSV/Excel files into a per-source dropzone; this module normalizes them into a common
revenue schema. It is a dropzone reader, not a live scraper — same pattern as
``scripts/ingest_prasa.py``.

Output schema (one row per agency-period-category aggregate):

    fiscal_year, service_domain, collecting_agency, revenue_category,
    amount, currency, source_type, pledged_debt_ref, municipality, source_file
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from scripts.config import PROJECT_ROOT, setup_logging

REVENUE_COLUMNS = [
    "fiscal_year",
    "service_domain",
    "collecting_agency",
    "revenue_category",
    "amount",
    "currency",
    "source_type",
    "pledged_debt_ref",
    "municipality",
    "source_file",
]

# Service domain -> aggregate public/ratepayer payer entity name. Mirrors the
# `public_ratepayers_<domain>` convention documented in docs/transaction_schema.md.
PUBLIC_PAYER_BY_DOMAIN = {
    "toll": "PUBLIC RATEPAYERS TOLL",
    "transit": "PUBLIC RATEPAYERS TRANSIT",
    "utility": "PUBLIC RATEPAYERS UTILITY",
    "port": "PUBLIC RATEPAYERS PORT",
}

# Service domain -> canonical inflow transaction_type (see docs/transaction_schema.md).
TRANSACTION_TYPE_BY_DOMAIN = {
    "toll": "toll_collection",
    "transit": "fare_collection",
    "utility": "utility_rate_revenue",
    "port": "port_fee_revenue",
}

COL_MAP = {
    "fiscal_year": [
        "Fiscal Year",
        "Año Fiscal",
        "FY",
        "Year",
        "Año",
        "fiscal_year",
        "anio_fiscal",
    ],
    "revenue_category": [
        "Revenue Category",
        "Category",
        "Categoría",
        "Concepto",
        "Revenue Type",
        "Tipo de Ingreso",
        "Ingreso",
        "revenue_category",
    ],
    "amount": [
        "Amount",
        "Monto",
        "Revenue",
        "Ingreso",
        "Gross Revenue",
        "Total",
        "Recaudo",
        "Recaudación",
        "amount",
    ],
    "source_type": [
        "Source Type",
        "Source",
        "Fuente",
        "source_type",
    ],
    "pledged_debt_ref": [
        "Pledged Debt",
        "Bond",
        "Bono",
        "Debt Reference",
        "pledged_debt_ref",
    ],
    "municipality": [
        "Municipality",
        "Municipio",
        "Plaza",
        "Location",
        "municipality",
        "municipio",
    ],
}

_NUM_RE = re.compile(r"[^0-9.\-]")


def _map_col(df_cols, candidates):
    cols_lower = {c.lower(): c for c in df_cols}
    for cand in candidates:
        if cand in df_cols:
            return cand
        if cand.lower() in cols_lower:
            return cols_lower[cand.lower()]
    return None


def _clean_amount(value):
    if value is None or pd.isna(value):
        return ""
    raw = _NUM_RE.sub("", str(value))
    return raw if raw not in ("", "-", ".") else ""


def _read_file(path, logger):
    suffix = path.suffix.lower()
    try:
        if suffix in (".xlsx", ".xls"):
            xl = pd.ExcelFile(path)
            best = pd.DataFrame()
            for sheet in xl.sheet_names:
                try:
                    df = pd.read_excel(xl, sheet_name=sheet, dtype=str, na_filter=False)
                    if len(df) > len(best):
                        best = df
                except Exception:
                    pass
            logger.info(f"  Read {len(best):,} rows from {path.name}")
            return best
        elif suffix == ".csv":
            for enc in ("utf-8", "latin-1", "utf-8-sig"):
                try:
                    df = pd.read_csv(
                        path, dtype=str, na_filter=False, encoding=enc, low_memory=False
                    )
                    logger.info(f"  Read {len(df):,} rows from {path.name}")
                    return df
                except UnicodeDecodeError:
                    continue
        logger.warning(f"  Unsupported: {path.name}")
        return pd.DataFrame()
    except Exception as e:
        logger.warning(f"  Failed to read {path.name}: {e}")
        return pd.DataFrame()


def _parse_df(df, source_file, service_domain, collecting_agency, logger):
    if df.empty:
        return pd.DataFrame(columns=REVENUE_COLUMNS)

    out = {}
    for out_col, candidates in COL_MAP.items():
        src = _map_col(df.columns.tolist(), candidates)
        out[out_col] = df[src].fillna("").astype(str) if src else ""

    result = pd.DataFrame(out)
    result["amount"] = result["amount"].apply(_clean_amount)
    result["service_domain"] = service_domain
    result["collecting_agency"] = (
        result.get("collecting_agency", "") if "collecting_agency" in result else ""
    )
    # Allow a per-file agency column to override the default.
    agency_src = _map_col(df.columns.tolist(), ["Agency", "Agencia", "collecting_agency"])
    result["collecting_agency"] = (
        df[agency_src].fillna("").astype(str) if agency_src else collecting_agency
    )
    result.loc[result["collecting_agency"].str.strip() == "", "collecting_agency"] = (
        collecting_agency
    )
    result["currency"] = "USD"
    result["source_file"] = source_file

    for col in REVENUE_COLUMNS:
        if col not in result.columns:
            result[col] = ""

    result = result[result["amount"].str.strip() != ""]
    logger.info(f"  → {len(result):,} revenue rows from {source_file}")
    return result[REVENUE_COLUMNS]


def _find_files(drop_dir, logger):
    if not drop_dir.exists():
        logger.warning(f"  Dropzone not found: {drop_dir}")
        return []
    files = [
        f
        for f in sorted(drop_dir.iterdir())
        if f.suffix.lower() in (".csv", ".xlsx", ".xls") and not f.name.startswith("~")
    ]
    logger.info(f"  Found {len(files)} file(s) in {drop_dir}")
    return files


def _file_has_data(path):
    if not path.exists():
        return False
    try:
        return len(pd.read_csv(path, dtype=str, nrows=2)) > 0
    except Exception:
        return False


def run_revenue_ingest(
    *,
    logger_name,
    drop_subdir,
    out_filename,
    service_domain,
    collecting_agency,
    root=None,
    force=False,
):
    """Read a revenue dropzone and write the normalized revenue CSV.

    Returns ``{"rows", "path", "errors"}`` like the other producers.
    """
    if root is None:
        root = PROJECT_ROOT
    root = Path(root)
    out_path = root / "data" / "staging" / "processed" / out_filename
    drop_dir = root / drop_subdir
    logger = setup_logging(logger_name)
    logger.info(f"Starting {service_domain} revenue ingestion...")

    if not force and _file_has_data(out_path):
        rows = len(pd.read_csv(out_path, dtype=str, low_memory=False))
        logger.info(f"  {out_filename} exists ({rows:,} rows) — skipping.")
        return {"rows": rows, "path": str(out_path), "errors": []}

    files = _find_files(drop_dir, logger)
    if not files:
        logger.warning(f"  No files found. Place revenue exports in {drop_subdir}")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(columns=REVENUE_COLUMNS).to_csv(out_path, index=False, encoding="utf-8")
        return {"rows": 0, "path": str(out_path), "errors": [f"No files in {drop_subdir}"]}

    all_dfs = []
    errors = []
    for f in files:
        logger.info(f"  Processing {f.name}...")
        df_raw = _read_file(f, logger)
        df_out = _parse_df(df_raw, f.name, service_domain, collecting_agency, logger)
        if not df_out.empty:
            all_dfs.append(df_out)
        else:
            errors.append(f"No rows from {f.name}")

    if not all_dfs:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(columns=REVENUE_COLUMNS).to_csv(out_path, index=False, encoding="utf-8")
        return {"rows": 0, "path": str(out_path), "errors": errors or ["No data extracted"]}

    combined = pd.concat(all_dfs, ignore_index=True).drop_duplicates(
        subset=["fiscal_year", "collecting_agency", "revenue_category", "amount"]
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    combined.to_csv(out_path, index=False, encoding="utf-8")

    total_val = pd.to_numeric(combined["amount"], errors="coerce").fillna(0).sum()
    logger.info("=" * 60)
    logger.info(f"{service_domain.upper()} REVENUE SUMMARY")
    logger.info("=" * 60)
    logger.info(f"  Total revenue rows:  {len(combined):,}")
    logger.info(f"  Total gross revenue: ${total_val:,.0f}")

    return {"rows": len(combined), "path": str(out_path), "errors": errors}
