"""Shared read-only PR Grid V2 Cell_Profile API for federation consumers.

The router never generates geometry or Cell_IDs. It serves only receipt-verified
domain-owned Cell_Profile materializations and always emits the immutable
Spiderweb grid identity. Missing materialization is NO_DATA, never ZERO_RECORDS.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

ROOT = Path(__file__).resolve().parents[2]
SPATIAL = ROOT / "federation" / "spatial"
if str(SPATIAL) not in sys.path:
    sys.path.insert(0, str(SPATIAL))

from pr_grid_v2_runtime import (  # noqa: E402
    GRID_ID,
    GRID_VERSION,
    GridV2PinError,
    build_grid_deep_link,
    grid_identity,
    load_pin,
    validate_cell_id,
    validate_level,
)

router = APIRouter(prefix="/api/grid/v2", tags=["grid-v2"])
PIN_PATH = SPATIAL / "pr_grid_geographic_v2.pin.json"
FEDERATION_MANIFEST = ROOT / "federation.json"
PROFILE_ROOT_ENV = "PRII_GRID_V2_PROFILE_ROOT"
MAX_PROFILE_BYTES = 25_000_000


def _local_repository() -> str:
    try:
        payload = json.loads(FEDERATION_MANIFEST.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GridV2PinError(f"cannot read federation repository identity: {exc}") from exc
    full_name = payload.get("repository_full_name")
    if not isinstance(full_name, str) or "/" not in full_name:
        raise GridV2PinError("federation.json lacks repository_full_name")
    slug = full_name.rsplit("/", 1)[-1]
    if not slug:
        raise GridV2PinError("invalid repository_full_name")
    return slug


def _validated_pin(*, level: str):
    consumer = _local_repository()
    return load_pin(PIN_PATH, expected_consumer=consumer, required_level=level)


def _validate_profile_row(
    row: dict[str, Any],
    *,
    consumer: str,
    identity: dict[str, str],
    cell_id: str,
) -> None:
    if row.get("Repository") != consumer:
        raise ValueError("profile Repository mismatch")
    if row.get("Cell_ID") != cell_id:
        raise ValueError("profile Cell_ID mismatch")
    if row.get("Grid_Identity") != identity:
        raise ValueError("profile Grid_Identity mismatch")
    if row.get("Geometry_Included") is not False:
        raise ValueError("geometry must remain with Spiderweb")

    state = row.get("Data_State")
    count = row.get("Record_Count")
    if state not in ("HAS_RECORDS", "ZERO_RECORDS", "NO_DATA"):
        raise ValueError("invalid Data_State")
    if not isinstance(count, int) or isinstance(count, bool) or count < 0:
        raise ValueError("invalid Record_Count")
    if state == "HAS_RECORDS" and count <= 0:
        raise ValueError("HAS_RECORDS requires positive Record_Count")
    if state in ("ZERO_RECORDS", "NO_DATA") and count != 0:
        raise ValueError(f"{state} requires Record_Count=0")
    if state == "ZERO_RECORDS" and row.get("Coverage_State") != "VERIFIED":
        raise ValueError("ZERO_RECORDS requires VERIFIED coverage")


def _no_data_response(
    *,
    consumer: str,
    identity: dict[str, str],
    cell_id: str,
    level: str,
    storage_state: str,
) -> dict[str, Any]:
    pin = _validated_pin(level=level)
    return {
        "Grid_Identity": identity,
        "Repository": consumer,
        "Cell_ID": cell_id,
        "Data_State": "NO_DATA",
        "Coverage_State": "UNKNOWN",
        "Record_Count": 0,
        "Geometry_Included": False,
        "Profile_Storage_State": storage_state,
        "Grid_Deep_Link": build_grid_deep_link(pin, level=level, cell_id=cell_id),
    }


@router.get("/profile/{level}/{cell_id}")
def cell_profile(level: str, cell_id: str) -> dict[str, Any]:
    """Return one domain-owned Cell_Profile with mandatory immutable grid identity."""
    try:
        selected_level = validate_level(level)
        validated_cell = validate_cell_id(cell_id, level=selected_level)
        pin = _validated_pin(level=selected_level)
        consumer = pin.consumer
        identity = grid_identity(pin, level=selected_level, cell_id=validated_cell)
    except GridV2PinError as exc:
        raise HTTPException(
            status_code=503,
            detail="grid pin unavailable or incompatible: " + str(exc),
        ) from exc

    root_value = os.environ.get(PROFILE_ROOT_ENV)
    if root_value is None or not root_value.strip():
        return _no_data_response(
            consumer=consumer,
            identity=identity,
            cell_id=validated_cell,
            level=selected_level,
            storage_state="NOT_CONFIGURED",
        )

    path = Path(root_value) / consumer / f"{selected_level}.jsonl"
    receipt_path = path.with_suffix(".receipt.json")
    if not path.exists() or not receipt_path.exists():
        return _no_data_response(
            consumer=consumer,
            identity=identity,
            cell_id=validated_cell,
            level=selected_level,
            storage_state="CONFIGURED_MISSING_ARTIFACT",
        )
    if path.stat().st_size > MAX_PROFILE_BYTES:
        raise HTTPException(503, "profile artifact exceeds bounded read size")

    try:
        payload = path.read_bytes()
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        if not isinstance(receipt, dict):
            raise ValueError("profile receipt must be an object")
        base_identity = grid_identity(pin, level=selected_level)
        if receipt.get("Output_SHA256") != hashlib.sha256(payload).hexdigest():
            raise ValueError("profile Output_SHA256 mismatch")
        if receipt.get("Output_Bytes") not in (None, len(payload)):
            raise ValueError("profile Output_Bytes mismatch")
        if receipt.get("Repository") != consumer:
            raise ValueError("profile receipt Repository mismatch")
        if receipt.get("Grid_Identity") != base_identity:
            raise ValueError("profile receipt Grid_Identity mismatch")
        if receipt.get("Geometry_Copied") is not False:
            raise ValueError("profile receipt copied geometry")
        if receipt.get("State") != "CANDIDATE_NOT_CANONICAL":
            raise ValueError("profile receipt state is not admissible")

        found = None
        for raw in payload.decode("utf-8").splitlines():
            if not raw:
                continue
            row = json.loads(raw)
            if not isinstance(row, dict):
                raise ValueError("profile row must be an object")
            if row.get("Cell_ID") != validated_cell:
                continue
            if found is not None:
                raise ValueError("duplicate Cell_ID in profile artifact")
            _validate_profile_row(
                row,
                consumer=consumer,
                identity=identity,
                cell_id=validated_cell,
            )
            found = dict(row)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError, TypeError) as exc:
        raise HTTPException(503, "profile validation BLOCKED: " + str(exc)) from exc

    if found is None:
        return _no_data_response(
            consumer=consumer,
            identity=identity,
            cell_id=validated_cell,
            level=selected_level,
            storage_state="CONFIGURED",
        )

    found["Profile_Storage_State"] = "CONFIGURED"
    return found


@router.get("/identity/{level}")
def grid_identity_response(level: str) -> dict[str, Any]:
    """Expose the exact consumer pin identity without generating geometry."""
    try:
        selected_level = validate_level(level)
        pin = _validated_pin(level=selected_level)
        return {
            "Grid_Identity": grid_identity(pin, level=selected_level),
            "Repository": pin.consumer,
            "Geometry_Included": False,
            "Geometry_Authority": "spiderweb-pr",
            "Handoff_Template": (
                f"/grid/{GRID_ID}/{GRID_VERSION}/{selected_level}/<Cell_ID>"
            ),
        }
    except GridV2PinError as exc:
        raise HTTPException(
            status_code=503,
            detail="grid pin unavailable or incompatible: " + str(exc),
        ) from exc
