"""
Download all non-contract federal awards to/in Puerto Rico via USASpending bulk download.

Uses /api/v2/bulk_download/awards/ which has NO record limit (unlike spending_by_award
which silently caps at 10,000 records). Each pass submits one asynchronous job per
fiscal year, polls until the ZIP is ready, downloads it, and extracts the CSV.

Covers ALL awarding agencies (no agency filter) across three award type groups:
  grants  (02-05): block grants, formula grants, project grants, cooperative agreements
  direct  (06):    direct payments (specified use)
  loans   (07-08): direct and guaranteed loans

Four passes, split into restartable fiscal-year windows:
  grants_pop       — place of performance = PR, types 02-05
  grants_recipient — recipient located in PR, types 02-05
  direct_recipient — recipient located in PR, type 06
  loans_recipient  — recipient located in PR, types 07-08

Output:
  data/staging/raw/grants/grants_pop_fy<YYYY>.csv
  data/staging/raw/grants/grants_recipient_fy<YYYY>.csv
  data/staging/raw/grants/direct_recipient_fy<YYYY>.csv
  data/staging/raw/grants/loans_recipient_fy<YYYY>.csv
  data/staging/processed/pr_grants_master.csv

Usage:
  python3 scripts/download_grants.py                   # full run
  python3 scripts/download_grants.py --force           # re-download existing
  python3 scripts/download_grants.py --pass grants_pop # single pass only
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import sys
import time
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import requests

from scripts.config import PROJECT_ROOT, setup_logging
from scripts._download_utils import derive_fiscal_year as _derive_fiscal_year
from tools.keyless_execution_plan import (
    GRANTS_PASSES,
    GRANTS_START_FY,
    current_fiscal_year,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BULK_DOWNLOAD_URL = "https://api.usaspending.gov/api/v2/bulk_download/awards/"
BULK_STATUS_URL = "https://api.usaspending.gov/api/v2/bulk_download/status/"

# API constraint: date_range must be within one year (≤ 365/366 days per job).
# We use one job per fiscal year (Oct 1 → Sep 30).
START_FY = GRANTS_START_FY  # FY2000 = Oct 1999 - Sep 2000
END_FY = current_fiscal_year()


def _fy_windows(start_fy: int = START_FY, end_fy: int = END_FY) -> list[dict]:
    """Generate one dict per fiscal year: {label, start_date, end_date}."""
    return [
        {
            "label": str(fy),
            "start_date": f"{fy - 1}-10-01",
            "end_date": f"{fy}-09-30",
        }
        for fy in range(start_fy, end_fy + 1)
    ]


POLL_INTERVAL_S = 15
MAX_POLL_S = 1800  # 30 minutes

MAX_RETRIES = 3
RETRY_BACKOFF = [30, 60, 120]  # generous backoff — USASpending drops connections when flooded

CIRCUIT_BREAKER_THRESHOLD = 3  # consecutive failures before pausing
CIRCUIT_BREAKER_SLEEP_S = 2700  # 45 minutes — full USASpending rate-limit reset window

# (output_prefix, prime_award_types numeric codes, filter_type)
# bulk_download uses prime_award_types with the same numeric codes as spending_by_award
PASSES = [
    ("grants_pop", ["02", "03", "04", "05"], "pop"),
    ("grants_recipient", ["02", "03", "04", "05"], "recipient"),
    ("direct_recipient", ["06"], "recipient"),
    ("loans_recipient", ["07", "08"], "recipient"),
]
if tuple(prefix for prefix, _, _ in PASSES) != GRANTS_PASSES:
    raise RuntimeError("grants execution plan and downloader passes are out of sync")

# Bulk download CSVs use snake_case column names (different from spending_by_award fields)
BULK_RENAME = {
    "award_id_fain": "award_id",
    "recipient_name": "recipient_name",
    "recipient_uei": "recipient_uei",
    "awarding_agency_name": "awarding_agency",
    "awarding_sub_agency_name": "awarding_sub_agency",
    "total_obligated_amount": "obligated_amount",
    "period_of_performance_start_date": "award_date",
    "primary_place_of_performance_state_name": "pop_state",
    "primary_place_of_performance_county_name": "pop_county",
    "transaction_description": "description",
    "assistance_type_description": "award_category",
}

MASTER_COLUMNS = [
    "award_id",
    "recipient_name",
    "recipient_uei",
    "awarding_agency",
    "awarding_sub_agency",
    "obligated_amount",
    "award_date",
    "fiscal_year",
    "pop_state",
    "pop_county",
    "description",
    "source_file",
    "source_dataset",
    "award_category",
]


# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": "ContractSweeper/1.0", "Accept": "application/json"})
    return s


# ---------------------------------------------------------------------------
# Helpers (unchanged)
# ---------------------------------------------------------------------------


def _file_has_data(filepath: Path) -> bool:
    """Return True for a readable generated CSV with the exact canonical schema."""
    if not filepath.exists():
        return False
    try:
        header = pd.read_csv(filepath, dtype=str, nrows=0, low_memory=False)
        return list(header.columns) == MASTER_COLUMNS
    except Exception:
        return False


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _csv_metadata(path: Path) -> tuple[int | None, list[str], str | None]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.reader(handle, strict=True)
            try:
                columns = next(reader)
            except StopIteration:
                return None, [], "empty CSV without header"
            rows = sum(1 for _ in reader)
    except (OSError, UnicodeDecodeError, csv.Error) as exc:
        return None, [], f"{type(exc).__name__}: {exc}"
    return rows, columns, None


# ---------------------------------------------------------------------------
# Bulk download network layer
# ---------------------------------------------------------------------------


def _build_bulk_payload(prime_award_types: list, filter_type: str, window: dict) -> dict:
    """Build a bulk_download/awards/ request body for one pass + FY window."""
    if filter_type == "pop":
        location = {
            "place_of_performance_scope": "domestic",
            "place_of_performance_locations": [{"country": "USA", "state": "PR"}],
        }
    else:
        location = {
            "recipient_scope": "domestic",
            "recipient_locations": [{"country": "USA", "state": "PR"}],
        }
    return {
        "filters": {
            "prime_award_types": prime_award_types,
            "date_type": "action_date",
            "date_range": {"start_date": window["start_date"], "end_date": window["end_date"]},
            **location,
        },
        "columns": [],
        "file_format": "csv",
    }


def _submit_bulk_job(
    session: requests.Session,
    payload: dict,
    logger,
) -> dict | None:
    """POST to bulk_download/awards/. Returns the response dict or None on error."""
    last_err = None
    for attempt in range(MAX_RETRIES):
        try:
            resp = session.post(BULK_DOWNLOAD_URL, json=payload, timeout=60)
            if 400 <= resp.status_code < 500:
                logger.error(f"  Job submission HTTP {resp.status_code}: {resp.text[:300]}")
                return None
            if 500 <= resp.status_code < 600:
                resp.raise_for_status()
            resp.raise_for_status()
            return resp.json()
        except (requests.RequestException, ValueError) as e:
            last_err = e
        if attempt < MAX_RETRIES - 1:
            wait = RETRY_BACKOFF[attempt]
            logger.warning(
                f"  Submission attempt {attempt + 1} failed ({last_err}) — retrying in {wait}s"
            )
            time.sleep(wait)
    logger.error(f"  Job submission failed after {MAX_RETRIES} attempts: {last_err}")
    return None


def _poll_job(
    session: requests.Session,
    file_name: str,
    logger,
    timeout_s: int = MAX_POLL_S,
) -> str | None:
    """Poll the bulk download status endpoint until finished. Returns file_url or None."""
    deadline = time.time() + timeout_s
    elapsed = 0
    while time.time() < deadline:
        try:
            resp = session.get(
                BULK_STATUS_URL,
                params={"file_name": file_name},
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
        except (requests.RequestException, ValueError) as e:
            logger.warning(f"  Poll error ({e}) — retrying in {POLL_INTERVAL_S}s")
            time.sleep(POLL_INTERVAL_S)
            elapsed += POLL_INTERVAL_S
            continue

        status = data.get("status", "")
        total_rows = data.get("total_rows")

        if status == "finished":
            file_url = data.get("file_url") or data.get("download_url")
            rows_msg = f", {total_rows:,} rows" if total_rows else ""
            logger.info(f"  Job finished after {elapsed}s{rows_msg}")
            return file_url

        if status == "failed":
            logger.error(f"  Job failed: {data.get('message', 'no message')}")
            return None

        if elapsed % 60 == 0 and elapsed > 0:
            logger.info(f"  Still waiting... ({elapsed}s elapsed, status={status})")

        time.sleep(POLL_INTERVAL_S)
        elapsed += POLL_INTERVAL_S

    logger.error(f"  Job timed out after {timeout_s}s")
    return None


def _download_zip(
    session: requests.Session,
    file_url: str,
    zip_path: Path,
    logger,
) -> bool:
    """Stream-download the bulk ZIP file to disk. Returns True on success."""
    logger.info("  Downloading ZIP...")
    try:
        resp = session.get(file_url, timeout=(30, 1800), stream=True)
        resp.raise_for_status()
        zip_path.parent.mkdir(parents=True, exist_ok=True)
        with open(zip_path, "wb") as fh:
            for chunk in resp.iter_content(chunk_size=1 << 16):
                if chunk:
                    fh.write(chunk)
        size_mb = zip_path.stat().st_size / (1024 * 1024)
        logger.info(f"  ZIP saved: {zip_path.name} ({size_mb:.1f} MB)")
        return True
    except Exception as e:
        logger.error(f"  ZIP download failed: {e}")
        return False


def _extract_csv(zip_path: Path, logger) -> tuple[pd.DataFrame, str | None]:
    """Open a ZIP and distinguish valid empty CSVs from extraction failures."""
    try:
        with zipfile.ZipFile(zip_path) as zf:
            csv_names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
            if not csv_names:
                error = f"no CSV files found in {zip_path.name}"
                logger.error(f"  {error}")
                return pd.DataFrame(), error
            frames = []
            for name in csv_names:
                logger.info(f"  Extracting {name}")
                with zf.open(name) as f:
                    df = pd.read_csv(
                        io.TextIOWrapper(f, encoding="utf-8-sig"),
                        dtype=str,
                        low_memory=False,
                    )
                    frames.append(df)
                    logger.info(f"  {name}: {len(df):,} rows, {len(df.columns)} cols")
            return pd.concat(frames, ignore_index=True), None
    except Exception as e:
        logger.error(f"  ZIP extraction failed: {e}")
        return pd.DataFrame(), f"ZIP extraction failed: {type(e).__name__}: {e}"


def _normalize_bulk_df(df: pd.DataFrame, source_file: str) -> pd.DataFrame:
    """Map bulk download CSV columns to canonical MASTER_COLUMNS schema."""
    if df.empty:
        return pd.DataFrame(columns=MASTER_COLUMNS)

    # Apply rename map for known columns; warn about any missing expected fields
    matched = {k for k in BULK_RENAME if k in df.columns}
    unmatched = set(BULK_RENAME) - matched
    if unmatched:
        import logging

        logging.getLogger("download_grants").warning(
            f"  BULK_RENAME: {len(unmatched)} expected columns not found: {sorted(unmatched)}"
        )
    df = df.rename(columns={k: v for k, v in BULK_RENAME.items() if k in df.columns})

    # award_id: prefer award_id_fain (already renamed above); fallback to assistance_award_unique_key
    _fallback_key = "assistance_award_unique_key"
    if "award_id" in df.columns:
        empty_mask = df["award_id"].isna() | (df["award_id"].str.strip() == "")
        if empty_mask.any() and _fallback_key in df.columns:
            df.loc[empty_mask, "award_id"] = df.loc[empty_mask, _fallback_key]
    elif _fallback_key in df.columns:
        df["award_id"] = df[_fallback_key]

    # fiscal_year: use authoritative field from USASpending; derive as fallback
    if "action_date_fiscal_year" in df.columns:
        df["fiscal_year"] = df["action_date_fiscal_year"].astype(str).str.strip()
    elif "award_date" in df.columns:
        df["fiscal_year"] = df["award_date"].apply(_derive_fiscal_year)
    else:
        df["fiscal_year"] = ""

    df["source_file"] = source_file
    df["source_dataset"] = "grants"

    for col in MASTER_COLUMNS:
        if col not in df.columns:
            df[col] = ""

    return df[MASTER_COLUMNS]


# ---------------------------------------------------------------------------
# Per-pass downloader
# ---------------------------------------------------------------------------


def _run_one_window(
    session: requests.Session,
    prefix: str,
    type_codes: list,
    filter_type: str,
    window: dict,
    raw_dir: Path,
    force: bool,
    logger,
) -> dict:
    """Submit, poll, download, and extract one FY window for one pass."""
    fy = window["label"]
    fname = f"{prefix}_fy{fy}.csv"
    csv_path = raw_dir / fname
    zip_path = raw_dir / f"{prefix}_fy{fy}.zip"
    result = {"fy": fy, "rows": 0, "error": None, "skipped": False}

    if not force and _file_has_data(csv_path):
        try:
            rows = len(pd.read_csv(csv_path, dtype=str, low_memory=False))
        except Exception:
            rows = 0
        logger.info(f"    Skipping {fname} (exists, {rows:,} rows)")
        result["rows"] = rows
        result["skipped"] = True
        return result

    payload = _build_bulk_payload(type_codes, filter_type, window)
    job = _submit_bulk_job(session, payload, logger)
    if job is None:
        result["error"] = "job submission failed"
        return result

    file_name = job.get("file_name") or job.get("file_url", "").split("/")[-1]
    status = job.get("status", "")
    file_url = job.get("file_url") or job.get("download_url")

    if status != "finished" or not file_url:
        file_url = _poll_job(session, file_name, logger)

    if not file_url:
        result["error"] = "job did not complete"
        return result

    zip_ok = False
    for attempt in range(MAX_RETRIES):
        if _download_zip(session, file_url, zip_path, logger):
            zip_ok = True
            break
        if attempt < MAX_RETRIES - 1:
            wait = RETRY_BACKOFF[attempt]
            logger.warning(f"  ZIP download attempt {attempt + 1} failed — retrying in {wait}s")
            time.sleep(wait)
    if not zip_ok:
        result["error"] = "ZIP download failed after 3 attempts"
        return result

    df, extraction_error = _extract_csv(zip_path, logger)
    try:
        zip_path.unlink()
    except Exception:
        pass

    if extraction_error is not None:
        result["error"] = extraction_error
        return result

    if df.empty:
        # Empty is valid (no awards for PR in that FY) — write header-only CSV
        pd.DataFrame(columns=MASTER_COLUMNS).to_csv(csv_path, index=False, encoding="utf-8")
        return result

    df_master = _normalize_bulk_df(df, fname)
    raw_dir.mkdir(parents=True, exist_ok=True)
    df_master.to_csv(csv_path, index=False, encoding="utf-8")
    result["rows"] = len(df_master)
    logger.info(f"    FY{fy}: {len(df_master):,} rows → {fname}")
    return result


def download_pass(
    session: requests.Session,
    prefix: str,
    type_codes: list,
    filter_type: str,
    raw_dir: Path,
    force: bool,
    logger,
    fy_start: int | None = None,
    fy_end: int | None = None,
) -> dict:
    """Run all FY windows for one pass. Returns aggregate stats dict."""
    effective_start = fy_start if fy_start is not None else START_FY
    effective_end = fy_end if fy_end is not None else END_FY
    if effective_end < effective_start:
        raise ValueError("fy_end must be greater than or equal to fy_start")
    windows = _fy_windows(effective_start, effective_end)

    stats: dict = {"prefix": prefix, "rows": 0, "errors": [], "api_calls": 0}
    logger.info(f"  [{prefix}] Running {len(windows)} FY windows (filter={filter_type})")

    consecutive_failures = 0
    prev_was_api_call = False

    for i, window in enumerate(windows):
        if i > 0 and prev_was_api_call:
            time.sleep(10)  # only throttle between real API submissions

        if consecutive_failures >= CIRCUIT_BREAKER_THRESHOLD:
            logger.warning(
                f"  [{prefix}] {consecutive_failures} consecutive failures — "
                f"sleeping {CIRCUIT_BREAKER_SLEEP_S // 60} min to let API recover..."
            )
            time.sleep(CIRCUIT_BREAKER_SLEEP_S)
            consecutive_failures = 0

        result = _run_one_window(
            session,
            prefix,
            type_codes,
            filter_type,
            window,
            raw_dir,
            force,
            logger,
        )
        stats["rows"] += result["rows"]
        prev_was_api_call = not result.get("skipped", False)
        if prev_was_api_call:
            stats["api_calls"] += 1
        if result["error"]:
            consecutive_failures += 1
            stats["errors"].append(f"FY{result['fy']}: {result['error']}")
        elif not result.get("skipped"):
            consecutive_failures = 0

    logger.info(f"  [{prefix}] Total: {stats['rows']:,} rows, {len(stats['errors'])} errors")
    return stats


# ---------------------------------------------------------------------------
# Master build (unchanged)
# ---------------------------------------------------------------------------


def build_master(
    raw_dir: Path,
    master_path: Path,
    logger,
    *,
    files: list[Path] | None = None,
) -> int:
    """Concatenate all raw CSVs, deduplicate by award_id, write master."""
    files = sorted(files if files is not None else raw_dir.glob("*.csv"))
    if not files:
        logger.warning("  No raw grant files found — master not written")
        return 0

    frames = []
    for f in files:
        try:
            df = pd.read_csv(f, dtype=str, low_memory=False)
            frames.append(df)
        except Exception as e:
            raise RuntimeError(f"cannot build grants master from {f.name}: {e}") from e

    if not frames:
        logger.warning("  No data loaded — master not written")
        return 0

    combined = pd.concat(frames, ignore_index=True)
    before = len(combined)
    logger.info(f"  Combined: {before:,} rows before dedup")

    if "award_id" in combined.columns:
        identifiers = combined["award_id"].fillna("").astype(str).str.strip()
        duplicate_identifiers = identifiers.ne("") & identifiers.duplicated(keep="first")
        combined = combined.loc[~duplicate_identifiers]
        removed = before - len(combined)
        if removed:
            logger.info(f"  Removed {removed:,} duplicate award_id rows")

    master_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = master_path.with_name(f".{master_path.name}.tmp")
    try:
        combined.to_csv(temporary_path, index=False, encoding="utf-8")
        temporary_path.replace(master_path)
    finally:
        temporary_path.unlink(missing_ok=True)
    logger.info(f"  Master written: {len(combined):,} rows → {master_path.name}")
    return len(combined)


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------


def run(root: Path | None = None) -> dict:
    """Main entry point (no --force). Returns summary dict."""
    return _run(
        root=root,
        force=False,
        only_pass=None,
        fy_start=_environment_fiscal_year("MONEYSWEEP_GRANTS_START_FY"),
        fy_end=_environment_fiscal_year("MONEYSWEEP_GRANTS_END_FY"),
    )


def _environment_fiscal_year(name: str) -> int | None:
    value = os.environ.get(name)
    if value is None or not value.strip():
        return None
    try:
        fiscal_year = int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if fiscal_year < 1900:
        raise ValueError(f"{name} must be at least 1900")
    return fiscal_year


def _run(
    root: Path | None = None,
    force: bool = False,
    only_pass: str | None = None,
    fy_start: int | None = None,
    fy_end: int | None = None,
    build_master_output: bool = True,
) -> dict:
    root = Path(root or PROJECT_ROOT).expanduser().resolve()

    raw_dir = root / "data" / "staging" / "raw" / "grants"
    master_path = root / "data" / "staging" / "processed" / "pr_grants_master.csv"
    raw_dir.mkdir(parents=True, exist_ok=True)

    logger = setup_logging("download_grants")
    effective_start = fy_start if fy_start is not None else START_FY
    effective_end = fy_end if fy_end is not None else END_FY
    if effective_end < effective_start:
        return {
            "schema_version": "moneysweep.grants_download/v2",
            "only_pass": only_pass,
            "fy_start": effective_start,
            "fy_end": effective_end,
            "raw_rows": 0,
            "master_rows": 0,
            "master_path": str(master_path),
            "master_built": False,
            "raw_dir": str(raw_dir),
            "errors": ["fy_end must be greater than or equal to fy_start"],
            "passes": [],
            "expected_raw_files": [],
            "missing_raw_files": [],
            "raw_files": [],
        }
    fy_range = f"FY{effective_start}–FY{effective_end}"
    logger.info(f"Starting PR all-agency awards bulk download ({fy_range})...")

    passes = PASSES
    if only_pass:
        passes = [(p, t, f) for p, t, f in PASSES if p == only_pass]
        if not passes:
            logger.error(f"  Unknown pass '{only_pass}'. Valid: {[p for p, _, _ in PASSES]}")
            return {
                "schema_version": "moneysweep.grants_download/v2",
                "only_pass": only_pass,
                "fy_start": effective_start,
                "fy_end": effective_end,
                "raw_rows": 0,
                "master_rows": 0,
                "master_path": str(master_path),
                "master_built": False,
                "raw_dir": str(raw_dir),
                "errors": [f"unknown pass: {only_pass}"],
                "passes": [],
                "expected_raw_files": [],
                "missing_raw_files": [],
                "raw_files": [],
            }

    all_errors = []
    total_rows = 0
    pass_stats: list[dict] = []
    session = _session()
    try:
        for i, (prefix, type_codes, filter_type) in enumerate(passes):
            if i > 0 and pass_stats[-1].get("api_calls", 0) > 0:
                logger.info("  Sleeping 10 min between passes to let API recover...")
                time.sleep(600)
            logger.info(f"\n[Pass: {prefix}] types={type_codes}, filter={filter_type}")
            try:
                stats = download_pass(
                    session,
                    prefix,
                    type_codes,
                    filter_type,
                    raw_dir,
                    force,
                    logger,
                    fy_start=fy_start,
                    fy_end=fy_end,
                )
            except Exception as e:
                logger.error(f"  Unexpected error on {prefix}: {e}")
                stats = {
                    "prefix": prefix,
                    "rows": 0,
                    "errors": [str(e)],
                    "api_calls": 0,
                }

            total_rows += stats["rows"]
            all_errors.extend(stats.get("errors", []))
            pass_stats.append(stats)
    finally:
        session.close()

    expected_raw_files = [
        raw_dir / f"{prefix}_fy{fy}.csv"
        for prefix, _, _ in passes
        for fy in range(effective_start, effective_end + 1)
    ]
    missing_raw_files = [
        path.relative_to(root).as_posix() for path in expected_raw_files if not path.is_file()
    ]
    raw_files = []
    for path in expected_raw_files:
        if not path.is_file():
            continue
        digest = _sha256_file(path)
        rows, columns, metadata_error = _csv_metadata(path)
        relative = path.relative_to(root).as_posix()
        if metadata_error is not None:
            all_errors.append(f"invalid raw output: {relative}: {metadata_error}")
        elif columns != MASTER_COLUMNS:
            all_errors.append(f"invalid raw schema: {relative}")
        raw_files.append(
            {
                "path": relative,
                "sha256": digest,
                "bytes": path.stat().st_size,
                "rows": rows,
                "columns": columns,
            }
        )
    if missing_raw_files:
        all_errors.extend(f"missing raw output: {path}" for path in missing_raw_files)

    master_rows = 0
    master_built = False
    if build_master_output and not all_errors:
        logger.info("\nBuilding grants master...")
        try:
            master_rows = build_master(
                raw_dir,
                master_path,
                logger,
                files=expected_raw_files,
            )
        except (OSError, UnicodeError, ValueError, RuntimeError) as exc:
            all_errors.append(f"master build failed: {type(exc).__name__}: {exc}")
        else:
            master_built = master_path.is_file()
            if not master_built:
                all_errors.append("master output was not created")

    summary = {
        "schema_version": "moneysweep.grants_download/v2",
        "only_pass": only_pass,
        "fy_start": effective_start,
        "fy_end": effective_end,
        "raw_rows": total_rows,
        "master_rows": master_rows,
        "master_path": str(master_path),
        "master_built": master_built,
        "raw_dir": str(raw_dir),
        "errors": all_errors,
        "passes": pass_stats,
        "expected_raw_files": [path.relative_to(root).as_posix() for path in expected_raw_files],
        "missing_raw_files": missing_raw_files,
        "raw_files": raw_files,
    }

    logger.info("=" * 60)
    logger.info("GRANTS BULK DOWNLOAD SUMMARY")
    logger.info("=" * 60)
    logger.info(f"  Raw rows:    {total_rows:,}")
    logger.info(f"  Master rows: {master_rows:,}")
    logger.info(f"  Errors:      {len(all_errors)}")
    for err in all_errors:
        logger.warning(f"    {err}")

    return summary


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Download all non-contract PR federal awards via USASpending bulk download"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-download even if raw CSV already exists",
    )
    parser.add_argument(
        "--pass",
        dest="only_pass",
        metavar="PASS",
        help=f"Run only one pass. Choices: {[p for p, _, _ in PASSES]}",
    )
    parser.add_argument(
        "--fy-start",
        type=int,
        metavar="YEAR",
        help=f"Only download FY >= YEAR (e.g. 2020). Default: {START_FY}",
    )
    parser.add_argument(
        "--fy-end",
        type=int,
        metavar="YEAR",
        help=f"Only download FY <= YEAR. Default: {END_FY}",
    )
    parser.add_argument(
        "--skip-master",
        action="store_true",
        help="Write fiscal-year raw files without building a partial master.",
    )
    parser.add_argument(
        "--summary-path",
        type=Path,
        help="Write the complete execution summary as JSON.",
    )
    args = parser.parse_args()

    summary = _run(
        force=args.force,
        only_pass=args.only_pass,
        fy_start=args.fy_start,
        fy_end=args.fy_end,
        build_master_output=not args.skip_master,
    )
    if args.summary_path is not None:
        args.summary_path.parent.mkdir(parents=True, exist_ok=True)
        args.summary_path.write_text(
            json.dumps(summary, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    print("\nGrants bulk download complete.")
    print(f"  Raw rows:    {summary['raw_rows']:,}")
    print(f"  Master rows: {summary['master_rows']:,}")
    if summary.get("master_built"):
        print(f"  Master path: {summary['master_path']}")
    if summary["errors"]:
        print(f"  Errors ({len(summary['errors'])}):")
        for err in summary["errors"]:
            print(f"    {err}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
