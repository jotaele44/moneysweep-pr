#!/usr/bin/env python3
"""Acquire and adjudicate the Puerto Rico federal financial-assistance denominator.

This is deliberately separate from ``download_grants.py``.  The existing grants
master is a compatibility projection and drops native identifiers needed for
federal-financial-ontology certification.

Shard mode downloads one fiscal-year / Puerto-Rico-nexus slice from the
USAspending bulk award endpoint and preserves every native CSV field.  Aggregate
mode requires a complete shard receipt set, deduplicates awards by hard native
identifiers, and assigns every current SAM financial program a PR nexus state.

No canonical FAIN backfill is performed here.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import time
import zipfile
from datetime import date
from pathlib import Path

import pandas as pd
import requests

BULK_DOWNLOAD_URL = "https://api.usaspending.gov/api/v2/bulk_download/awards/"
BULK_STATUS_URL = "https://api.usaspending.gov/api/v2/bulk_download/status/"
# USAspending Advanced Search's financial-assistance filter denominator.  The
# ontology also carries F001-F010 source/reference aliases, but those are not
# duplicated here as filter values because the public Advanced Filter contract
# exposes the legacy 02-11 family for assistance searches.
ASSISTANCE_FILTER_CODES = ["02", "03", "04", "05", "06", "07", "08", "09", "10", "11"]
FINANCIAL_TOKENS = (
    "GRANT",
    "COOPERATIVE AGREEMENT",
    "DIRECT PAYMENT",
    "LOAN",
    "INSURANCE",
    "FINANCIAL ASSISTANCE",
    "SALE, EXCHANGE, OR DONATION",
)
POLL_SECONDS = 10
POLL_TIMEOUT_SECONDS = 1800

PROGRAM_COLUMN_CANDIDATES = (
    "assistance_listing_number",
    "cfda_number",
    "program_number",
)
AWARD_KEY_CANDIDATES = (
    "assistance_award_unique_key",
    "generated_unique_award_id",
    "award_id_fain",
    "fain",
    "uri",
)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _current_fy() -> int:
    today = date.today()
    return today.year + 1 if today.month >= 10 else today.year


def _window(fy: int) -> dict[str, str]:
    return {"start_date": f"{fy - 1}-10-01", "end_date": f"{fy}-09-30"}


def _payload(fy: int, nexus: str) -> dict:
    location: dict[str, object]
    if nexus == "recipient":
        location = {
            "recipient_scope": "domestic",
            "recipient_locations": [{"country": "USA", "state": "PR"}],
        }
    elif nexus == "pop":
        location = {
            "place_of_performance_scope": "domestic",
            "place_of_performance_locations": [{"country": "USA", "state": "PR"}],
        }
    else:
        raise ValueError(f"unsupported nexus: {nexus}")
    return {
        "filters": {
            "prime_award_types": ASSISTANCE_FILTER_CODES,
            "date_type": "action_date",
            "date_range": _window(fy),
            **location,
        },
        "columns": [],
        "file_format": "csv",
    }


def _session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {"Accept": "application/json", "User-Agent": "moneysweep-pr-assistance-denominator/1"}
    )
    return session


def _submit_and_wait(session: requests.Session, payload: dict) -> str:
    response = session.post(BULK_DOWNLOAD_URL, json=payload, timeout=60)
    response.raise_for_status()
    job = response.json()
    file_url = job.get("file_url") or job.get("download_url")
    if job.get("status") == "finished" and file_url:
        return str(file_url)

    file_name = job.get("file_name")
    if not file_name:
        raise RuntimeError(f"USAspending bulk job missing file_name: {job}")
    deadline = time.time() + POLL_TIMEOUT_SECONDS
    while time.time() < deadline:
        status_response = session.get(BULK_STATUS_URL, params={"file_name": file_name}, timeout=30)
        status_response.raise_for_status()
        status = status_response.json()
        if status.get("status") == "finished":
            file_url = status.get("file_url") or status.get("download_url")
            if not file_url:
                raise RuntimeError("finished USAspending job has no download URL")
            return str(file_url)
        if status.get("status") == "failed":
            raise RuntimeError(f"USAspending bulk job failed: {status}")
        time.sleep(POLL_SECONDS)
    raise TimeoutError(f"USAspending bulk job timed out: {file_name}")


def _read_zip(content: bytes) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        for member in sorted(archive.namelist()):
            if not member.lower().endswith(".csv"):
                continue
            with archive.open(member) as handle:
                frames.append(
                    pd.read_csv(
                        io.TextIOWrapper(handle, encoding="utf-8-sig"),
                        dtype=str,
                        low_memory=False,
                    )
                )
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def run_shard(fy: int, nexus: str, output_dir: Path) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = f"pr_assistance_{nexus}_fy{fy}"
    csv_path = output_dir / f"{stem}.csv"
    receipt_path = output_dir / f"{stem}.receipt.json"
    session = _session()
    result: dict[str, object] = {
        "schema_version": "pr_assistance_shard_receipt_v1",
        "fiscal_year": fy,
        "nexus": nexus,
        "status": "failed",
        "rows": 0,
        "award_type_codes": ASSISTANCE_FILTER_CODES,
        "date_window": _window(fy),
    }
    try:
        file_url = _submit_and_wait(session, _payload(fy, nexus))
        response = session.get(file_url, timeout=(30, 1800))
        response.raise_for_status()
        frame = _read_zip(response.content)
        frame["moneysweep_pr_nexus_evidence"] = nexus
        frame["moneysweep_source_fiscal_year"] = str(fy)
        frame.to_csv(csv_path, index=False, encoding="utf-8")
        result.update(
            {
                "status": "complete",
                "rows": int(len(frame)),
                "column_count": int(len(frame.columns)),
                "csv_sha256": _sha256(csv_path),
            }
        )
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    receipt_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if result["status"] != "complete":
        raise RuntimeError(str(result.get("error", "shard failed")))
    return result


def _first_present(columns: set[str], candidates: tuple[str, ...]) -> str | None:
    for candidate in candidates:
        if candidate in columns:
            return candidate
    return None


def _program_number(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def _load_sam_financial_programs(
    sam_path: Path,
    expected_sha256: str,
    expected_artifact_sha256: str | None = None,
) -> dict[str, dict]:
    if not sam_path.exists():
        raise RuntimeError(f"frozen SAM denominator source is missing: {sam_path}")
    if expected_artifact_sha256 is not None:
        observed_artifact_hash = _sha256(sam_path)
        if observed_artifact_hash != expected_artifact_sha256:
            raise RuntimeError(
                "SAM denominator artifact drift: "
                f"expected {expected_artifact_sha256}, observed {observed_artifact_hash}"
            )
    if sam_path.suffix == ".gz":
        with gzip.open(sam_path, "rb") as source:
            source_bytes = source.read()
    else:
        source_bytes = sam_path.read_bytes()
    observed_hash = hashlib.sha256(source_bytes).hexdigest()
    if observed_hash != expected_sha256:
        raise RuntimeError(
            f"SAM denominator source drift: expected {expected_sha256}, observed {observed_hash}"
        )
    programs: dict[str, dict] = {}
    with io.StringIO(source_bytes.decode("cp1252"), newline="") as handle:
        for row in csv.DictReader(handle):
            assistance = (row.get("Types of Assistance (060)") or "").upper()
            if not any(token in assistance for token in FINANCIAL_TOKENS):
                continue
            number = (row.get("Program Number") or "").strip()
            if not number or number in programs:
                if number in programs:
                    raise RuntimeError(f"duplicate SAM Program Number: {number}")
                raise RuntimeError("blank SAM Program Number in financial denominator")
            programs[number] = row
    return programs


def aggregate(
    input_dir: Path,
    output_dir: Path,
    snapshot_path: Path,
    sam_path: Path,
    start_fy: int,
    end_fy: int,
) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    expected_sam_sha = snapshot["source"]["sha256"]
    programs = _load_sam_financial_programs(
        sam_path,
        expected_sam_sha,
        snapshot["source"].get("artifact_sha256"),
    )
    expected_programs = int(snapshot["denominator"]["financial_program_rows"])
    if len(programs) != expected_programs:
        raise RuntimeError(
            f"SAM financial denominator mismatch: {len(programs)} != {expected_programs}"
        )

    receipts = []
    frames: list[pd.DataFrame] = []
    for receipt_path in sorted(input_dir.rglob("*.receipt.json")):
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        receipts.append(receipt)
    expected_keys = {
        (fy, nexus) for fy in range(start_fy, end_fy + 1) for nexus in ("recipient", "pop")
    }
    complete_receipts = [r for r in receipts if r.get("status") == "complete"]
    complete_keys = [(int(r["fiscal_year"]), str(r["nexus"])) for r in complete_receipts]
    shard_keys = set(complete_keys)
    missing_keys = expected_keys - shard_keys
    extra_keys = shard_keys - expected_keys
    duplicate_keys = sorted(key for key in shard_keys if complete_keys.count(key) > 1)
    if missing_keys or extra_keys or duplicate_keys:
        raise RuntimeError(
            "incomplete shard denominator: "
            f"missing={sorted(missing_keys)}, extra={sorted(extra_keys)}, "
            f"duplicates={duplicate_keys}"
        )
    expected_shards = len(expected_keys)

    for csv_path in sorted(input_dir.rglob("pr_assistance_*_fy*.csv")):
        try:
            frame = pd.read_csv(csv_path, dtype=str, low_memory=False)
        except pd.errors.EmptyDataError:
            continue
        if not frame.empty:
            frames.append(frame)
    awards = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    columns = set(awards.columns)
    program_col = _first_present(columns, PROGRAM_COLUMN_CANDIDATES)
    if not awards.empty and program_col is None:
        raise RuntimeError(
            f"USAspending native extract lacks a program-number field; columns={sorted(columns)}"
        )

    if awards.empty:
        awards["moneysweep_program_number"] = pd.Series(dtype=str)
        awards["moneysweep_hard_award_key"] = pd.Series(dtype=str)
    else:
        awards["moneysweep_program_number"] = awards[program_col].map(_program_number)
        key_col = _first_present(columns, AWARD_KEY_CANDIDATES)
        if key_col is None:
            raise RuntimeError("USAspending native extract lacks every hard award-key candidate")
        awards["moneysweep_hard_award_key"] = awards[key_col].fillna("").astype(str).str.strip()
        if (awards["moneysweep_hard_award_key"] == "").any():
            raise RuntimeError(f"blank hard award key encountered using {key_col}")

        nexus = (
            awards.groupby("moneysweep_hard_award_key")["moneysweep_pr_nexus_evidence"]
            .agg(lambda values: ";".join(sorted(set(map(str, values)))))
            .rename("moneysweep_pr_nexus_evidence_set")
        )
        awards = awards.sort_values(
            ["moneysweep_hard_award_key", "moneysweep_source_fiscal_year"]
        ).drop_duplicates("moneysweep_hard_award_key", keep="last")
        awards = awards.merge(nexus, on="moneysweep_hard_award_key", how="left")

    observed_programs = set(awards.get("moneysweep_program_number", pd.Series(dtype=str))) - {""}
    confirmed = observed_programs & set(programs)
    orphan_program_numbers = sorted(observed_programs - set(programs))

    ledger_rows = []
    for number in sorted(programs):
        row = programs[number]
        if number in confirmed:
            state = "confirmed_pr_activity"
            evidence = "usaspending_pr_prime_assistance_denominator_v1"
        else:
            # A complete award search establishes no recovered award activity, but
            # does not by itself establish territorial eligibility/non-applicability.
            state = "unresolved"
            evidence = "complete_award_search_no_exact_program_binding"
        ledger_rows.append(
            {
                "program_number": number,
                "program_title": (row.get("Program Title") or "").strip(),
                "federal_agency": (row.get("Federal Agency (030)") or "").strip(),
                "pr_nexus_state": state,
                "evidence_ref": evidence,
            }
        )
    ledger = pd.DataFrame(ledger_rows)
    state_counts = ledger["pr_nexus_state"].value_counts().to_dict()

    awards_path = output_dir / "pr_assistance_prime_awards_native_dedup.csv"
    ledger_path = output_dir / "pr_financial_program_pr_nexus_adjudication.csv"
    coverage_path = output_dir / "pr_assistance_denominator_coverage.json"
    awards.to_csv(awards_path, index=False, encoding="utf-8")
    ledger.to_csv(ledger_path, index=False, encoding="utf-8")

    coverage = {
        "schema_version": "pr_assistance_denominator_coverage_v1",
        "sam_source_sha256": expected_sam_sha,
        "financial_program_denominator": len(programs),
        "programs_classified": len(ledger),
        "program_classification_pct": round(100.0 * len(ledger) / len(programs), 8),
        "pr_nexus_state_counts": state_counts,
        "complete_shards": len(shard_keys),
        "expected_shards": expected_shards,
        "native_rows_before_dedup": int(sum(int(r.get("rows", 0)) for r in complete_receipts)),
        "deduplicated_prime_awards": int(len(awards)),
        "confirmed_program_numbers": len(confirmed),
        "orphan_observed_program_numbers": orphan_program_numbers,
        "awards_missing_program_number": int(
            (awards.get("moneysweep_program_number", pd.Series(dtype=str)) == "").sum()
        ),
        "global_fain_backfill_allowed": False,
        "fain_backfill_blockers": [
            "subaward_denominator_not_yet_joined",
            "program_eligibility_nonactivity_adjudication_incomplete"
            if state_counts.get("unresolved", 0)
            else None,
            "orphan_program_number_conflicts" if orphan_program_numbers else None,
        ],
    }
    coverage["fain_backfill_blockers"] = [x for x in coverage["fain_backfill_blockers"] if x]
    coverage_path.write_text(
        json.dumps(coverage, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return coverage


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    shard = sub.add_parser("shard")
    shard.add_argument("--fy", type=int, required=True)
    shard.add_argument("--nexus", choices=("recipient", "pop"), required=True)
    shard.add_argument("--output-dir", type=Path, required=True)

    agg = sub.add_parser("aggregate")
    agg.add_argument("--input-dir", type=Path, required=True)
    agg.add_argument("--output-dir", type=Path, required=True)
    agg.add_argument(
        "--snapshot",
        type=Path,
        default=Path("data/reference/federal_financial_program_denominator_20260827.json"),
    )
    agg.add_argument(
        "--sam-source",
        type=Path,
        default=Path("data/reference/AssistanceListings_DataGov_c32925ccdefe425d.csv.gz"),
    )
    agg.add_argument("--start-fy", type=int, default=2000)
    agg.add_argument("--end-fy", type=int, default=_current_fy())

    args = parser.parse_args()
    if args.command == "shard":
        result = run_shard(args.fy, args.nexus, args.output_dir)
    else:
        result = aggregate(
            args.input_dir,
            args.output_dir,
            args.snapshot,
            args.sam_source,
            args.start_fy,
            args.end_fy,
        )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
