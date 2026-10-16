"""Page-resumable FEC Schedule B acquisition for the certified PR committee universe."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import requests

from scripts.config import PROJECT_ROOT, setup_logging

FEC_URL = "https://api.open.fec.gov/v1/schedules/schedule_b/"
START_CYCLE = 2000
PAGE_SIZE = 100
MAX_ATTEMPTS = 8
CONNECT_TIMEOUT = 10
READ_TIMEOUT = 30
COLUMNS = [
    "cycle",
    "committee_id",
    "committee_name",
    "recipient_name",
    "recipient_committee_id",
    "disbursement_amount",
    "disbursement_date",
    "disbursement_description",
    "line_number",
    "image_number",
    "file_number",
    "sub_id",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def current_cycle() -> int:
    year = date.today().year
    return year if year % 2 == 0 else year + 1


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def committee_ids(path: Path) -> list[str]:
    if not path.exists():
        raise RuntimeError(f"Certified committee universe is missing: {path}")
    frame = pd.read_csv(path, dtype=str, low_memory=False)
    if "committee_id" not in frame.columns:
        raise RuntimeError("Certified committee universe lacks committee_id")
    values = list(
        dict.fromkeys(v.strip() for v in frame["committee_id"].dropna().astype(str) if v.strip())
    )
    if not values:
        raise RuntimeError("Certified committee universe is empty")
    return values


def request_json(session: requests.Session, params: dict[str, Any], logger: Any) -> dict[str, Any]:
    delay = 5.0
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = session.get(FEC_URL, params=params, timeout=(CONNECT_TIMEOUT, READ_TIMEOUT))
            if response.status_code == 429:
                retry_after = response.headers.get("Retry-After", "")
                wait = float(retry_after) if retry_after.isdigit() else max(60.0, delay)
                logger.warning("Rate limited; retrying in %.1fs", wait)
                time.sleep(wait)
                continue
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise RuntimeError("Schedule B response was not a JSON object")
            return payload
        except (requests.Timeout, requests.ConnectionError, requests.HTTPError) as exc:
            if attempt == MAX_ATTEMPTS:
                raise RuntimeError(
                    f"Schedule B request failed after {MAX_ATTEMPTS} attempts: {exc}"
                ) from exc
            logger.warning(
                "Schedule B request attempt %s/%s failed: %s; retrying in %.1fs",
                attempt,
                MAX_ATTEMPTS,
                type(exc).__name__,
                delay,
            )
            time.sleep(delay)
            delay = min(delay * 2, 120.0)
    raise RuntimeError("unreachable retry state")


def normalize_rows(results: list[Any], cycle: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for raw in results:
        if not isinstance(raw, dict):
            continue
        rows.append(
            {
                "cycle": cycle,
                "committee_id": raw.get("committee_id", ""),
                "committee_name": raw.get("committee", {}).get("name", "")
                if isinstance(raw.get("committee"), dict)
                else raw.get("committee_name", ""),
                "recipient_name": raw.get("recipient_name", ""),
                "recipient_committee_id": raw.get("recipient_committee_id", ""),
                "disbursement_amount": raw.get("disbursement_amount", ""),
                "disbursement_date": raw.get("disbursement_date", ""),
                "disbursement_description": raw.get("disbursement_description", ""),
                "line_number": raw.get("line_number", ""),
                "image_number": raw.get("image_number", ""),
                "file_number": raw.get("file_number", ""),
                "sub_id": raw.get("sub_id", ""),
            }
        )
    return rows


def checkpoint_path(root: Path, cycle: int, committee_id: str, page: int) -> Path:
    return root / f"cycle={cycle}" / f"committee={committee_id}" / f"page={page:06d}.csv"


def valid_checkpoint(path: Path, receipt: dict[str, Any]) -> bool:
    return (
        path.exists()
        and receipt.get("sha256") == sha256_file(path)
        and int(receipt.get("rows", -1)) == len(pd.read_csv(path, dtype=str, low_memory=False))
    )


def assemble(checkpoint_dir: Path, output: Path) -> pd.DataFrame:
    files = sorted(checkpoint_dir.glob("cycle=*/committee=*/page=*.csv"))
    frames = [pd.read_csv(path, dtype=str, low_memory=False) for path in files]
    frame = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=COLUMNS)
    for column in COLUMNS:
        if column not in frame.columns:
            frame[column] = ""
    frame = frame[COLUMNS].drop_duplicates().reset_index(drop=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    frame.to_csv(temporary, index=False, encoding="utf-8")
    temporary.replace(output)
    return frame


def run(root: Path, resume: bool) -> dict[str, Any]:
    logger = setup_logging("download_fec_schedule_b_resumable")
    processed = root / "data/staging/processed"
    committees = committee_ids(processed / "pr_fec_committees.csv")
    output = processed / "pr_fec_disbursements.csv"
    checkpoint_dir = root / "data/checkpoints/campaign_finance/fec_schedule_b"
    manifest_path = root / "data/manifests/campaign_finance/fec_schedule_b_acquisition.json"
    if not resume and checkpoint_dir.exists():
        for path in sorted(checkpoint_dir.glob("**/*"), reverse=True):
            if path.is_file():
                path.unlink()
            elif path.is_dir():
                path.rmdir()

    cycles = list(range(START_CYCLE, current_cycle() + 1, 2))
    manifest: dict[str, Any] = {
        "manifest_type": "fec_schedule_b_acquisition",
        "status": "running",
        "started_at": utc_now(),
        "query_scope": "certified_pr_committee_ids",
        "committee_count": len(committees),
        "planned_cycles": cycles,
        "planned_batches": len(cycles) * len(committees),
        "completed_batches": 0,
        "page_receipts": {},
        "resume": resume,
    }
    if resume and manifest_path.exists():
        previous = json.loads(manifest_path.read_text(encoding="utf-8"))
        if isinstance(previous.get("page_receipts"), dict):
            manifest["page_receipts"] = previous["page_receipts"]
            manifest["resumed_from_started_at"] = previous.get("started_at")
    write_json(manifest_path, manifest)

    api_key = os.environ.get("FEC_API_KEY")
    if not api_key:
        raise RuntimeError("FEC_API_KEY is required")
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "MoneySweep/1.0 campaign-finance materialization",
            "Accept": "application/json",
            "X-Api-Key": api_key,
        }
    )
    completed = 0
    try:
        for cycle in cycles:
            for committee_id in committees:
                page = 1
                total_pages = 1
                while page <= total_pages:
                    key = f"{cycle}/{committee_id}/{page}"
                    path = checkpoint_path(checkpoint_dir, cycle, committee_id, page)
                    receipt = manifest["page_receipts"].get(key, {})
                    if resume and valid_checkpoint(path, receipt):
                        total_pages = int(receipt["total_pages"])
                        page += 1
                        continue
                    payload = request_json(
                        session,
                        {
                            "committee_id": committee_id,
                            "two_year_transaction_period": cycle,
                            "per_page": PAGE_SIZE,
                            "page": page,
                            "sort": "-disbursement_date",
                            "sort_hide_null": "false",
                        },
                        logger,
                    )
                    results = payload.get("results", [])
                    pagination = payload.get("pagination", {})
                    if not isinstance(results, list) or not isinstance(pagination, dict):
                        raise RuntimeError("Invalid Schedule B response schema")
                    total_pages = int(pagination.get("pages", 1) or 1)
                    rows = normalize_rows(results, cycle)
                    path.parent.mkdir(parents=True, exist_ok=True)
                    temporary = path.with_suffix(".csv.tmp")
                    pd.DataFrame(rows, columns=COLUMNS).to_csv(
                        temporary, index=False, encoding="utf-8"
                    )
                    temporary.replace(path)
                    manifest["page_receipts"][key] = {
                        "cycle": cycle,
                        "committee_id": committee_id,
                        "page": page,
                        "total_pages": total_pages,
                        "rows": len(rows),
                        "sha256": sha256_file(path),
                        "checkpointed_at": utc_now(),
                    }
                    write_json(manifest_path, manifest)
                    page += 1
                completed += 1
                manifest["completed_batches"] = completed
                manifest["last_checkpoint_at"] = utc_now()
                write_json(manifest_path, manifest)
    finally:
        session.close()

    frame = assemble(checkpoint_dir, output)
    manifest.update(
        {
            "status": "complete",
            "completed_at": utc_now(),
            "completed_batches": manifest["planned_batches"],
            "rows": len(frame),
            "output_sha256": sha256_file(output),
            "schema_columns": COLUMNS,
            "checkpoint_pages": len(manifest["page_receipts"]),
            "checkpoint_rows": sum(
                int(item["rows"]) for item in manifest["page_receipts"].values()
            ),
        }
    )
    write_json(manifest_path, manifest)
    print(json.dumps(manifest, sort_keys=True))
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    result = run(args.root, args.resume)
    return 0 if result["status"] == "complete" and result["rows"] > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
