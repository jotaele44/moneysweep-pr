#!/usr/bin/env python3
"""Recover failed Puerto Rico assistance-denominator shards without changing semantics.

The canonical denominator remains one fiscal-year x PR-nexus shard.  This recovery
runner changes only acquisition mechanics: it tolerates USAspending bulk-status
registration lag and recursively bisects date ranges when a bulk job itself ends
in ``failed`` state.  Recovered ranges are recombined into the same native CSV
shape and one canonical FY/nexus receipt.
"""

from __future__ import annotations

import argparse
import copy
import json
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import requests

from scripts.download_pr_assistance_denominator import (
    ASSISTANCE_FILTER_CODES,
    BULK_DOWNLOAD_URL,
    BULK_STATUS_URL,
    _payload,
    _read_zip,
    _session,
    _sha256,
    _window,
)

POLL_SECONDS = 10
REGISTRATION_GRACE_SECONDS = 180
POLL_TIMEOUT_SECONDS = 1800
MAX_SPLIT_DEPTH = 6
MIN_SPLIT_DAYS = 14
SUBMIT_ATTEMPTS = 4
TRANSIENT_HTTP = {404, 408, 425, 429, 500, 502, 503, 504}


class BulkJobFailed(RuntimeError):
    """USAspending accepted a bulk job but later marked it failed."""

    def __init__(self, status: dict):
        self.status = status
        super().__init__(f"USAspending bulk job failed: {status}")


def _iso(value: date) -> str:
    return value.isoformat()


def _dates(fy: int) -> tuple[date, date]:
    window = _window(fy)
    return date.fromisoformat(window["start_date"]), date.fromisoformat(window["end_date"])


def _payload_for_range(fy: int, nexus: str, start: date, end: date) -> dict:
    payload = copy.deepcopy(_payload(fy, nexus))
    payload["filters"]["date_range"] = {
        "start_date": _iso(start),
        "end_date": _iso(end),
    }
    return payload


def _post_job(session: requests.Session, payload: dict) -> dict:
    last_error: Exception | None = None
    for attempt in range(1, SUBMIT_ATTEMPTS + 1):
        try:
            response = session.post(BULK_DOWNLOAD_URL, json=payload, timeout=60)
            if response.status_code in TRANSIENT_HTTP and response.status_code != 404:
                raise requests.HTTPError(
                    f"transient HTTP {response.status_code}", response=response
                )
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, ValueError) as exc:
            last_error = exc
            if attempt == SUBMIT_ATTEMPTS:
                break
            time.sleep(min(30, 2**attempt))
    raise RuntimeError(f"USAspending bulk submission failed after retries: {last_error}")


def _wait_for_job(session: requests.Session, job: dict) -> tuple[str, dict]:
    file_url = job.get("file_url") or job.get("download_url")
    if job.get("status") == "finished" and file_url:
        return str(file_url), job

    file_name = job.get("file_name")
    if not file_name:
        raise RuntimeError(f"USAspending bulk job missing file_name: {job}")

    started = time.monotonic()
    deadline = started + POLL_TIMEOUT_SECONDS
    registration_deadline = started + REGISTRATION_GRACE_SECONDS
    last_status: dict | None = None
    while time.monotonic() < deadline:
        try:
            response = session.get(BULK_STATUS_URL, params={"file_name": file_name}, timeout=30)
            if response.status_code == 404 and time.monotonic() < registration_deadline:
                time.sleep(POLL_SECONDS)
                continue
            if response.status_code == 404:
                raise RuntimeError(
                    f"USAspending bulk job remained unregistered after grace period: {file_name}"
                )
            if response.status_code in TRANSIENT_HTTP:
                time.sleep(POLL_SECONDS)
                continue
            response.raise_for_status()
            status = response.json()
            last_status = status
        except (requests.RequestException, ValueError):
            time.sleep(POLL_SECONDS)
            continue

        state = status.get("status")
        if state == "finished":
            url = status.get("file_url") or status.get("download_url")
            if not url:
                raise RuntimeError("finished USAspending job has no download URL")
            return str(url), status
        if state == "failed":
            raise BulkJobFailed(status)
        time.sleep(POLL_SECONDS)

    raise TimeoutError(f"USAspending bulk job timed out: {file_name}; last_status={last_status}")


def _download_frame(session: requests.Session, url: str) -> pd.DataFrame:
    last_error: Exception | None = None
    for attempt in range(1, 4):
        try:
            response = session.get(url, timeout=(30, 1800))
            response.raise_for_status()
            return _read_zip(response.content)
        except requests.RequestException as exc:
            last_error = exc
            if attempt == 3:
                break
            time.sleep(5 * attempt)
    raise RuntimeError(f"USAspending artifact download failed: {last_error}")


def _acquire_range(
    session: requests.Session,
    *,
    fy: int,
    nexus: str,
    start: date,
    end: date,
    depth: int,
    audit: list[dict],
) -> list[pd.DataFrame]:
    record = {
        "start_date": _iso(start),
        "end_date": _iso(end),
        "depth": depth,
        "status": "submitted",
    }
    audit.append(record)
    try:
        job = _post_job(session, _payload_for_range(fy, nexus, start, end))
        record["file_name"] = job.get("file_name")
        url, status = _wait_for_job(session, job)
        frame = _download_frame(session, url)
        record.update(
            {
                "status": "complete",
                "rows": int(len(frame)),
                "file_name": status.get("file_name") or record.get("file_name"),
                "total_rows_reported": status.get("total_rows"),
                "seconds_elapsed": status.get("seconds_elapsed"),
            }
        )
        return [frame]
    except BulkJobFailed as exc:
        record.update({"status": "bulk_failed", "failure": exc.status})
        span_days = (end - start).days + 1
        if depth >= MAX_SPLIT_DEPTH or span_days <= MIN_SPLIT_DAYS:
            raise
        midpoint = start + timedelta(days=(span_days // 2) - 1)
        right_start = midpoint + timedelta(days=1)
        record["recovery"] = "bisect"
        return _acquire_range(
            session,
            fy=fy,
            nexus=nexus,
            start=start,
            end=midpoint,
            depth=depth + 1,
            audit=audit,
        ) + _acquire_range(
            session,
            fy=fy,
            nexus=nexus,
            start=right_start,
            end=end,
            depth=depth + 1,
            audit=audit,
        )
    except Exception as exc:
        record.update({"status": "failed", "error": f"{type(exc).__name__}: {exc}"})
        raise


def recover_shard(fy: int, nexus: str, output_dir: Path) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = f"pr_assistance_{nexus}_fy{fy}"
    csv_path = output_dir / f"{stem}.csv"
    receipt_path = output_dir / f"{stem}.receipt.json"
    start, end = _dates(fy)
    audit: list[dict] = []
    result: dict[str, object] = {
        "schema_version": "pr_assistance_shard_receipt_v1",
        "recovery_schema_version": "pr_assistance_shard_recovery_v1",
        "fiscal_year": fy,
        "nexus": nexus,
        "status": "failed",
        "rows": 0,
        "award_type_codes": ASSISTANCE_FILTER_CODES,
        "date_window": _window(fy),
        "recovery_strategy": "404_registration_retry_then_recursive_date_bisection",
        "range_attempts": audit,
        "acquired_at_utc": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
    }

    try:
        session = _session()
        frames = _acquire_range(
            session,
            fy=fy,
            nexus=nexus,
            start=start,
            end=end,
            depth=0,
            audit=audit,
        )
        frame = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
        frame["moneysweep_pr_nexus_evidence"] = nexus
        frame["moneysweep_source_fiscal_year"] = str(fy)
        frame.to_csv(csv_path, index=False, encoding="utf-8")
        result.update(
            {
                "status": "complete",
                "rows": int(len(frame)),
                "column_count": int(len(frame.columns)),
                "csv_sha256": _sha256(csv_path),
                "successful_leaf_ranges": sum(
                    1 for item in audit if item.get("status") == "complete"
                ),
                "bulk_failed_ranges_recovered": sum(
                    1 for item in audit if item.get("status") == "bulk_failed"
                ),
            }
        )
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"

    receipt_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if result["status"] != "complete":
        raise RuntimeError(str(result.get("error", "recovery shard failed")))
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fy", type=int, required=True)
    parser.add_argument("--nexus", choices=("recipient", "pop"), required=True)
    parser.add_argument("--output-dir", type=Path, default=Path("artifact"))
    args = parser.parse_args()
    result = recover_shard(args.fy, args.nexus, args.output_dir)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
