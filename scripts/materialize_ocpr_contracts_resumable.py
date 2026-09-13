#!/usr/bin/env python3
"""Resumable, checkpointed materialization for the OCPR contract registry.

Pages are appended to an isolated JSONL work file. A deterministic checkpoint
binds source URL, page length, next offset, observed total, row count, and the
SHA-256 of the work file. The canonical CSV is replaced only after a clean full
run; smoke or interrupted runs remain provisional and cannot masquerade as a
complete source.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from scripts import scrape_ocpr_contracts as ocpr
from scripts.config import PROJECT_ROOT, setup_logging
from scripts.ingest_ocpr_contracts import OUTPUT_COLUMNS

STATE_DIR_REL = "data/staging/checkpoints/ocpr_contracts"
OUT_PATH_REL = ocpr.OUT_PATH_REL
SCHEMA_VERSION = "ocpr_resumable_checkpoint_v1"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def paths(root: Path) -> tuple[Path, Path, Path]:
    state_dir = root / STATE_DIR_REL
    return (
        state_dir / "checkpoint.json",
        state_dir / "pages.jsonl",
        state_dir / "completion_receipt.json",
    )


def atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def initial_checkpoint(page_length: int) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "source_url": ocpr.SEARCH_URL,
        "page_length": page_length,
        "next_offset": 0,
        "observed_total": None,
        "written_rows": 0,
        "pages_completed": 0,
        "work_sha256": None,
        "status": "IN_PROGRESS",
        "updated_at": utc_now(),
    }


def load_checkpoint(checkpoint_path: Path, work_path: Path, page_length: int, reset: bool) -> dict:
    if reset:
        checkpoint_path.unlink(missing_ok=True)
        work_path.unlink(missing_ok=True)
    if not checkpoint_path.exists():
        return initial_checkpoint(page_length)
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    if checkpoint.get("schema_version") != SCHEMA_VERSION:
        raise RuntimeError("Unsupported OCPR checkpoint schema")
    if checkpoint.get("source_url") != ocpr.SEARCH_URL:
        raise RuntimeError("Checkpoint source URL does not match configured OCPR endpoint")
    if int(checkpoint.get("page_length", 0)) != page_length:
        raise RuntimeError("Checkpoint page length differs; use --reset to start a new run")
    if checkpoint.get("written_rows", 0):
        if not work_path.exists():
            raise RuntimeError("Checkpoint references rows but work file is missing")
        actual = sha256(work_path)
        if checkpoint.get("work_sha256") != actual:
            raise RuntimeError("Checkpoint work-file SHA-256 mismatch")
    return checkpoint


def append_rows(work_path: Path, rows: list[dict]) -> None:
    work_path.parent.mkdir(parents=True, exist_ok=True)
    with work_path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def fetch_page_with_reauth(session, token, offset: int, page_length: int, logger):
    data = ocpr._fetch_page(session, token, offset, page_length, logger)
    if data is not None:
        return session, token, data
    logger.warning("Page failed; re-authenticating once before fail-closed stop")
    session.close()
    session, token = ocpr._session_and_token(logger)
    return session, token, ocpr._fetch_page(session, token, offset, page_length, logger)


def promote(root: Path, work_path: Path, checkpoint: dict, receipt_path: Path) -> dict:
    rows = []
    with work_path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"Malformed work JSONL at line {line_number}") from exc
    frame = pd.DataFrame(rows, columns=OUTPUT_COLUMNS)
    frame = frame[frame["contract_number"].astype(str).str.strip() != ""].drop_duplicates()
    observed_total = int(checkpoint["observed_total"])
    if len(rows) != observed_total:
        raise RuntimeError(
            f"Refusing promotion: fetched {len(rows)} rows but OCPR reported {observed_total}"
        )
    output = root / OUT_PATH_REL
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = output.with_suffix(output.suffix + ".tmp")
    frame.to_csv(tmp, index=False, encoding="utf-8")
    output_sha = sha256(tmp)
    os.replace(tmp, output)
    receipt = {
        "schema_version": "ocpr_completion_receipt_v1",
        "status": "COMPLETE",
        "source_url": ocpr.SEARCH_URL,
        "observed_total": observed_total,
        "raw_rows": len(rows),
        "canonical_rows": len(frame),
        "pages_completed": checkpoint["pages_completed"],
        "page_length": checkpoint["page_length"],
        "work_sha256": sha256(work_path),
        "output_path": OUT_PATH_REL,
        "output_sha256": output_sha,
        "completed_at": utc_now(),
    }
    atomic_json(receipt_path, receipt)
    return receipt


def run(root: Path, page_length: int, max_pages: int | None, reset: bool) -> dict:
    logger = setup_logging("materialize_ocpr_contracts_resumable")
    checkpoint_path, work_path, receipt_path = paths(root)
    checkpoint = load_checkpoint(checkpoint_path, work_path, page_length, reset)
    receipt_path.unlink(missing_ok=True)
    session, token = ocpr._session_and_token(logger)
    pages_this_run = 0
    try:
        while True:
            offset = int(checkpoint["next_offset"])
            session, token, data = fetch_page_with_reauth(
                session, token, offset, page_length, logger
            )
            if data is None:
                checkpoint.update(status="BLOCKED_PAGE_FETCH", updated_at=utc_now())
                atomic_json(checkpoint_path, checkpoint)
                return checkpoint
            # OCPR's current DataTables contract reports the returned page size in
            # recordsTotal and the complete unfiltered registry size in
            # recordsFiltered. Using recordsTotal first can falsely promote a
            # one-page smoke as a complete registry.
            reported_total = int(data.get("recordsFiltered") or data.get("recordsTotal") or 0)
            if reported_total <= 0:
                checkpoint.update(status="BLOCKED_INVALID_TOTAL", updated_at=utc_now())
                atomic_json(checkpoint_path, checkpoint)
                return checkpoint
            if checkpoint["observed_total"] is None:
                checkpoint["observed_total"] = reported_total
            elif int(checkpoint["observed_total"]) != reported_total:
                checkpoint.update(
                    status="BLOCKED_TOTAL_CHANGED",
                    updated_at=utc_now(),
                    latest_total=reported_total,
                )
                atomic_json(checkpoint_path, checkpoint)
                return checkpoint
            records = data.get("data") or []
            normalized = [ocpr._normalize_row(record) for record in records]
            append_rows(work_path, normalized)
            checkpoint["written_rows"] = int(checkpoint["written_rows"]) + len(normalized)
            checkpoint["pages_completed"] = int(checkpoint["pages_completed"]) + 1
            checkpoint["next_offset"] = offset + len(records)
            checkpoint["work_sha256"] = sha256(work_path)
            checkpoint["updated_at"] = utc_now()
            checkpoint["status"] = "IN_PROGRESS"
            atomic_json(checkpoint_path, checkpoint)
            pages_this_run += 1
            if not records or checkpoint["next_offset"] >= checkpoint["observed_total"]:
                checkpoint["status"] = "FETCH_COMPLETE"
                atomic_json(checkpoint_path, checkpoint)
                receipt = promote(root, work_path, checkpoint, receipt_path)
                checkpoint["status"] = "COMPLETE"
                checkpoint["updated_at"] = utc_now()
                atomic_json(checkpoint_path, checkpoint)
                return receipt
            if max_pages is not None and pages_this_run >= max_pages:
                checkpoint["status"] = "PROVISIONAL_MAX_PAGES"
                checkpoint["updated_at"] = utc_now()
                atomic_json(checkpoint_path, checkpoint)
                return checkpoint
    finally:
        session.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--page-length", type=int, default=ocpr.DEFAULT_PAGE_LENGTH)
    parser.add_argument("--max-pages", type=int)
    parser.add_argument("--reset", action="store_true")
    args = parser.parse_args()
    if args.page_length <= 0:
        parser.error("--page-length must be positive")
    result = run(args.root.resolve(), args.page_length, args.max_pages, args.reset)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("status") in {"COMPLETE", "PROVISIONAL_MAX_PAGES"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
