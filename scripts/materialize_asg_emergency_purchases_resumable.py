#!/usr/bin/env python3
"""Restartable materialization for the ASG emergency-purchase registry.

Pages are appended to an isolated JSONL work file and are never promoted to the
canonical staging CSV until the complete live page denominator closes. The
checkpoint binds page order, declared page count, row count, last-page
signature, and the SHA-256 of the work file.

The authoritative completeness ordering is `-numerocontrol`, which is stable
across the 2026-10-04 144-page verification. The default `-creado` ordering is
retained only for recency observations because concurrent page requests can
shift rows between pages and produced duplicate control numbers during the same
crawl.

A partial or interrupted run therefore cannot masquerade as a complete source.
The completion receipt measures the exact current row denominator but does not
itself authorize a leaderboard; identity/amount residue is adjudicated
separately by audit_asg_emergency_identity_coverage.py.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from scripts import scrape_asg_emergency_purchases as asg
from scripts.config import PROJECT_ROOT, setup_logging

STATE_DIR_REL = "data/staging/checkpoints/asg_emergency_purchases"
OUT_PATH_REL = asg.OUT_PATH_REL
SCHEMA_VERSION = "asg_emergency_resumable_checkpoint_v2"
ORDER_BY = "-numerocontrol"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def paths(root: Path) -> tuple[Path, Path, Path]:
    state = root / STATE_DIR_REL
    return (
        state / "checkpoint.json",
        state / "pages.jsonl",
        state / "completion_receipt.json",
    )


def atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp, path)


def initial_checkpoint() -> dict:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "sourceUrl": asg.BASE_URL,
        "ordering": ORDER_BY,
        "nextPage": 1,
        "declaredPages": None,
        "writtenRawRows": 0,
        "pagesCompleted": 0,
        "lastPageSignatureSha256": None,
        "workSha256": None,
        "status": "IN_PROGRESS",
        "updatedAt": utc_now(),
    }


def load_checkpoint(checkpoint_path: Path, work_path: Path, reset: bool) -> dict:
    if reset:
        checkpoint_path.unlink(missing_ok=True)
        work_path.unlink(missing_ok=True)
    if not checkpoint_path.exists():
        return initial_checkpoint()
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    if checkpoint.get("schemaVersion") != SCHEMA_VERSION:
        raise RuntimeError("Unsupported ASG checkpoint schema")
    if checkpoint.get("sourceUrl") != asg.BASE_URL:
        raise RuntimeError("Checkpoint source URL does not match configured ASG endpoint")
    if checkpoint.get("ordering") != ORDER_BY:
        raise RuntimeError("Checkpoint ordering contract changed")
    if checkpoint.get("writtenRawRows", 0):
        if not work_path.exists():
            raise RuntimeError("Checkpoint references rows but work file is missing")
        if checkpoint.get("workSha256") != sha256(work_path):
            raise RuntimeError("Checkpoint work-file SHA-256 mismatch")
    return checkpoint


def page_signature(records: list[dict]) -> str:
    controls = [asg._clean(record.get("Número de Control ASG")) for record in records]
    rendered = "\n".join(controls).encode("utf-8")
    return hashlib.sha256(rendered).hexdigest()


def append_rows(work_path: Path, rows: list[dict]) -> None:
    work_path.parent.mkdir(parents=True, exist_ok=True)
    with work_path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def promote(root: Path, work_path: Path, checkpoint: dict, receipt_path: Path) -> dict:
    declared_pages = int(checkpoint.get("declaredPages") or 0)
    if declared_pages <= 0 or int(checkpoint.get("pagesCompleted") or 0) != declared_pages:
        raise RuntimeError("Refusing promotion: page denominator is not closed")

    rows: list[dict] = []
    with work_path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"Malformed ASG work JSONL at line {line_number}") from exc

    if len(rows) != int(checkpoint.get("writtenRawRows") or 0):
        raise RuntimeError("Refusing promotion: work row count differs from checkpoint")

    controls = [str(row.get("control_number") or "").strip() for row in rows]
    if any(not value for value in controls):
        raise RuntimeError("Refusing promotion: one or more rows lack control_number")

    canonical_by_control: dict[str, dict] = {}
    duplicate_manifestations = 0
    duplicate_groups: set[str] = set()
    for row in rows:
        control = str(row.get("control_number") or "").strip()
        payload = {key: row.get(key) for key in asg.EMERGENCY_PURCHASE_COLUMNS}
        existing = canonical_by_control.get(control)
        if existing is None:
            canonical_by_control[control] = payload
            continue
        if existing != payload:
            raise RuntimeError(
                f"Refusing promotion: conflicting payloads share control_number {control}"
            )
        duplicate_manifestations += 1
        duplicate_groups.add(control)

    canonical_rows = list(canonical_by_control.values())
    frame = pd.DataFrame(canonical_rows, columns=asg.EMERGENCY_PURCHASE_COLUMNS)
    output = root / OUT_PATH_REL
    output.parent.mkdir(parents=True, exist_ok=True)

    # Preserve prior first-seen observations before replacing an older materialization.
    frame = asg._carry_forward_first_seen(
        frame,
        output,
        datetime.now(timezone.utc).date().isoformat(),
    )
    frame = asg.apply_post_ingest(frame, source_id=asg.SOURCE_ID, root=root)

    temp = output.with_suffix(output.suffix + ".tmp")
    frame.to_csv(temp, index=False, encoding="utf-8")
    output_sha = sha256(temp)
    os.replace(temp, output)

    source_native = int(
        (
            frame["vendor_identity_state"].astype(str)
            == "SOURCE_NATIVE_ASG_LICITADOR_ID"
        ).sum()
    )
    name_only = int(
        (frame["vendor_identity_state"].astype(str) == "UNRESOLVED_NAME_ONLY").sum()
    )
    missing_vendor = int(
        (
            frame["vendor_identity_state"].astype(str)
            == "UNRESOLVED_MISSING_VENDOR"
        ).sum()
    )

    receipt = {
        "schemaVersion": "asg_emergency_completion_receipt_v1",
        "status": "COMPLETE",
        "sourceUrl": asg.BASE_URL,
        "ordering": ORDER_BY,
        "declaredPages": declared_pages,
        "rawRows": len(rows),
        "exactDuplicateManifestations": duplicate_manifestations,
        "exactDuplicateGroups": len(duplicate_groups),
        "authoritativeUniverseTotal": len(frame),
        "uniqueControlNumbers": len(canonical_by_control),
        "pagesCompleted": int(checkpoint["pagesCompleted"]),
        "workSha256": sha256(work_path),
        "outputPath": OUT_PATH_REL,
        "outputSha256": output_sha,
        "identityObservation": {
            "sourceNativeRows": source_native,
            "nameOnlyRows": name_only,
            "missingVendorRows": missing_vendor,
            "identityScheme": "asg_licitador_id",
        },
        "leaderboardCertificationEffect": "NONE",
        "completedAt": utc_now(),
    }
    atomic_json(receipt_path, receipt)
    return receipt


def run(root: Path, max_pages: int | None, reset: bool) -> dict:
    logger = setup_logging("materialize_asg_emergency_purchases_resumable")
    checkpoint_path, work_path, receipt_path = paths(root)
    checkpoint = load_checkpoint(checkpoint_path, work_path, reset)
    receipt_path.unlink(missing_ok=True)

    session = asg.build_session(asg.HTTP.user_agent, asg.HTTP.extra_headers)
    pages_this_run = 0
    try:
        while True:
            declared = checkpoint.get("declaredPages")
            next_page = int(checkpoint["nextPage"])
            if declared is not None and next_page > int(declared):
                receipt = promote(root, work_path, checkpoint, receipt_path)
                checkpoint["status"] = "COMPLETE"
                checkpoint["updatedAt"] = utc_now()
                atomic_json(checkpoint_path, checkpoint)
                return receipt

            html = asg._fetch_page(session, next_page, logger, order_by=ORDER_BY)
            if html is None:
                checkpoint.update(status="BLOCKED_PAGE_FETCH", updatedAt=utc_now())
                atomic_json(checkpoint_path, checkpoint)
                return checkpoint

            observed_pages = asg.declared_page_count(html)
            if not observed_pages or observed_pages <= 0:
                checkpoint.update(status="BLOCKED_INVALID_PAGE_COUNT", updatedAt=utc_now())
                atomic_json(checkpoint_path, checkpoint)
                return checkpoint
            if declared is None:
                checkpoint["declaredPages"] = int(observed_pages)
            elif int(declared) != int(observed_pages):
                checkpoint.update(
                    status="BLOCKED_PAGE_COUNT_CHANGED",
                    latestDeclaredPages=int(observed_pages),
                    updatedAt=utc_now(),
                )
                atomic_json(checkpoint_path, checkpoint)
                return checkpoint

            records = asg.parse_records(html)
            if not records:
                checkpoint.update(
                    status="BLOCKED_EMPTY_PAGE",
                    emptyPage=next_page,
                    updatedAt=utc_now(),
                )
                atomic_json(checkpoint_path, checkpoint)
                return checkpoint

            signature = page_signature(records)
            if signature == checkpoint.get("lastPageSignatureSha256"):
                checkpoint.update(
                    status="BLOCKED_REPEATED_PAGE",
                    repeatedPage=next_page,
                    updatedAt=utc_now(),
                )
                atomic_json(checkpoint_path, checkpoint)
                return checkpoint

            base_rank = int(checkpoint["writtenRawRows"])
            normalized = [
                asg._normalize_row(record, creado_rank=None)
                for record in records
            ]
            append_rows(work_path, normalized)

            checkpoint["writtenRawRows"] = base_rank + len(normalized)
            checkpoint["pagesCompleted"] = int(checkpoint["pagesCompleted"]) + 1
            checkpoint["nextPage"] = next_page + 1
            checkpoint["lastPageSignatureSha256"] = signature
            checkpoint["workSha256"] = sha256(work_path)
            checkpoint["status"] = "IN_PROGRESS"
            checkpoint["updatedAt"] = utc_now()
            atomic_json(checkpoint_path, checkpoint)
            pages_this_run += 1

            if max_pages is not None and pages_this_run >= max_pages:
                checkpoint["status"] = "PROVISIONAL_MAX_PAGES"
                checkpoint["updatedAt"] = utc_now()
                atomic_json(checkpoint_path, checkpoint)
                return checkpoint
    finally:
        session.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--max-pages", type=int)
    parser.add_argument("--reset", action="store_true")
    args = parser.parse_args()
    if args.max_pages is not None and args.max_pages <= 0:
        parser.error("--max-pages must be positive")
    result = run(args.root.resolve(), args.max_pages, args.reset)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("status") in {"COMPLETE", "PROVISIONAL_MAX_PAGES"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
