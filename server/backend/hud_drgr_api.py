"""Local source-audit snapshots shared by diagnostic and desktop applications."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from desktop.workspace import resource_root, workspace_root
from server.backend.api_keys import _require_local_request

router = APIRouter(
    prefix="/materialization",
    tags=["source-audits"],
    dependencies=[Depends(_require_local_request)],
)


def _workspace() -> Path:
    # GET never bootstraps or rewrites the desktop workspace.
    return workspace_root()


def _within(root: Path, path: Path) -> bool:
    return path.resolve().is_relative_to(root.resolve())


@router.get("/hud-drgr/audits")
def hud_drgr_audits():
    """Read preserved receipts only; never re-inspect mutable source files on GET."""
    from collections import Counter

    roots = {resource_root().resolve(), _workspace().resolve()}
    results = []
    for root in sorted(roots):
        for path in sorted(
            (root / "reports" / "live-readiness").glob("*/hud_drgr_authorized_pursuit_receipt.json")
        ):
            if not _within(root, path):
                continue
            item = {"path": str(path)}
            try:
                raw = path.read_bytes()
                item["sha256"] = hashlib.sha256(raw).hexdigest()
                receipt = json.loads(raw)
                rows = receipt["records"]
                if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
                    raise ValueError("records must be a list of objects")
                counts = Counter(row["classification"] for row in rows)
                arithmetic = receipt["arithmetic"]
                valid = (
                    receipt["receipt_type"] == "moneysweep_hud_drgr_authorized_pursuit"
                    and receipt["source_id"] == "hud_drgr_authorized"
                    and receipt["result_state"]
                    in {"FOUND_AUTHORIZED_CANDIDATE", "PARTIAL_UNRESOLVED"}
                    and (receipt.get("blocker") is None or isinstance(receipt["blocker"], str))
                    and isinstance(receipt["generated_at_utc"], str)
                    and bool(receipt["generated_at_utc"])
                    and all(isinstance(row["path"], str) and row["classification"] for row in rows)
                    and all(
                        type(arithmetic.get(key)) is int and arithmetic[key] >= 0
                        for key in ("total", "classified", "authorized_candidates")
                    )
                    and all(
                        type(value) is int and value >= 0
                        for value in receipt["classification_counts"].values()
                    )
                    and receipt.get("authorization", "UNPROVEN") == "UNPROVEN"
                    and receipt.get("identity_effect", "NONE") == "NONE"
                    and arithmetic["total"] == len(rows)
                    and arithmetic["classified"] == len(rows)
                    and arithmetic["authorized_candidates"]
                    == counts.get("FOUND_AUTHORIZED_CANDIDATE", 0)
                    and dict(counts) == receipt["classification_counts"]
                )
                if not valid:
                    raise ValueError("receipt contract mismatch")
                timestamp = datetime.fromisoformat(
                    receipt["generated_at_utc"].replace("Z", "+00:00")
                )
                if timestamp.tzinfo is None:
                    raise ValueError("receipt time has no timezone")
                for row in rows:
                    relative = row.get("snapshot_relative_path")
                    if relative is None:
                        continue  # Historical receipts did not retain source bytes.
                    snapshot = path.parent / relative
                    if not _within(path.parent / "inputs", snapshot):
                        raise ValueError("snapshot escaped its input directory")
                    frozen = snapshot.read_bytes()
                    if (
                        hashlib.sha256(frozen).hexdigest() != row["sha256"]
                        or len(frozen) != row["byte_size"]
                    ):
                        raise ValueError("frozen source bytes differ from receipt")
                item.update(state="VALID_RECEIPT", receipt=receipt, authorization="UNPROVEN")
            except (OSError, ValueError, KeyError, TypeError, AttributeError):
                item.update(
                    state="INVALID_RECEIPT", error="Receipt schema or arithmetic is invalid"
                )
            results.append(item)
    return {"audits": results, "source_refresh": False}


@router.post("/hud-drgr/audits")
def create_hud_drgr_audit():
    """Run the fixed local source audit in a new directory, preserving prior snapshots."""
    from scripts.audit_hud_drgr_authorized_sources import build_receipt

    directory = (
        _workspace()
        / "reports"
        / "live-readiness"
        / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_hud_drgr_" + uuid.uuid4().hex)
    )
    try:
        build_receipt(directory)
    except Exception as exc:
        raise HTTPException(500, "Audit failed; prior snapshots remain available") from exc
    return {"state": "SNAPSHOT_CREATED", "authorization": "UNPROVEN"}
