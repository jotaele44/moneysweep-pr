"""Dependency-light trust-boundary helpers for desktop materialization."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any


def write_offline_receipt(root: Path, receipt: dict[str, Any]) -> dict[str, Any]:
    """Atomically persist a receipt without deriving its path from request data."""
    receipt_id = uuid.uuid4().hex
    public_receipt = {**receipt, "receipt_id": receipt_id}
    receipt_dir = root / "receipts" / "offline_ingest"
    receipt_dir.mkdir(parents=True, exist_ok=True)
    receipt_path = receipt_dir / f"{receipt_id}.json"
    temp_path = receipt_dir / f".{receipt_id}.tmp"
    payload = json.dumps(public_receipt, indent=2) + "\n"
    try:
        temp_path.write_text(payload, encoding="utf-8")
        temp_path.replace(receipt_path)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise
    return public_receipt


def public_run_summary(summary: dict[str, Any]) -> dict[str, Any]:
    """Project a local runner receipt onto the non-sensitive API contract."""
    public: dict[str, Any] = {
        key: summary[key]
        for key in (
            "schema_version",
            "started_utc",
            "selected_count",
            "selected",
            "egress_ok",
            "dry_run",
            "status",
            "ok_count",
            "error_count",
        )
        if key in summary
    }
    public["ran"] = []
    for row in summary.get("ran") or []:
        if not isinstance(row, dict):
            continue
        projected = {key: row[key] for key in ("source", "status", "rows", "seconds") if key in row}
        status = projected.get("status")
        if status in {"ERROR", "IMPORT_ERROR", "NO_ENTRYPOINT"}:
            projected["error_code"] = status
        public["ran"].append(projected)
    return public
