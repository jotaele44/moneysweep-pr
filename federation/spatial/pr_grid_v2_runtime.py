"""Fail-closed runtime contract for PR_GRID_GEOGRAPHIC_V2 RC1.

This module is single-sourced from thehub-pr/federation-templates and rendered
byte-identically into federation consumers. Spiderweb remains the sole geometry
authority; consumers validate and reference its immutable grid contract.
"""
from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

PIN_SCHEMA_VERSION = "pr_grid_geographic_v2_consumer_pin/1.0"
GRID_ID = "PR_GRID_GEOGRAPHIC_V2"
GRID_VERSION = "2.0.0-rc1"
CRS = "EPSG:6566"
GEOMETRY_AUTHORITY = "spiderweb-pr"
AUTHORITY_REPOSITORY = "jotaele44/spiderweb-pr"
AUTHORITY_COMMIT = "0c66e13d14232c0d7cbcbc179b3655904777dc71"
AUTHORITY_MANIFEST_PATH = "registry/spatial/v2/pr_grid_geographic_v2.manifest.json"

GRID_MANIFEST_SHA256 = "8902af188ad449955119016f5747fe2393c582d9ed552fb03bcaecd9ab510aa4"
CELL_SCHEMA_SHA256 = "1c173aee4b21b9baa545b656735155f2236a87c436d467a12132ef53b2592f5d"
BINDING_SCHEMA_SHA256 = "dabc461e47134b3b150be9aeb23b3d0097563493b33b3187538255e06b16a022"
MASK_SCHEMA_SHA256 = "0b31b717d274b19686bf7f47edbabdaec31c86800f2ca7f1e73ffb663600978b"
BINDING_SCHEMA_VERSION = "pr-grid-v2-binding/1.0"
MASK_SCHEMA_VERSION = "pr-grid-v2-mask/1.0"

ALLOWED_LEVELS: tuple[str, ...] = ("L0", "L1", "L2", "L3")
EXPECTED_DEFAULT_LEVELS = {
    "aguayluz-pr": "L1",
    "skywatcher-pr": "L2",
    "ovnis-pr": "L1",
    "moneysweep-pr": "L1",
    "centinelas-pr": "L0",
    "thehub-pr": "L1",
}
EXPECTED_CONSUMERS = frozenset(EXPECTED_DEFAULT_LEVELS)
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_CELL_ID_RE = re.compile(r"^PRG2:(L[0-3]):R([0-9]{3}):C([0-9]{4})$")
LEVEL_DIMENSIONS = {
    "L0": (67, 171),
    "L1": (134, 342),
    "L2": (268, 684),
    "L3": (536, 1368),
}


class GridV2PinError(ValueError):
    """Raised when a consumer pin is absent, malformed, stale, or incompatible."""


@dataclass(frozen=True)
class GridV2Pin:
    consumer: str
    default_level: str
    allowed_levels: tuple[str, ...]
    payload: Mapping[str, Any]


def _expect_equal(
    errors: list[str],
    payload: Mapping[str, Any],
    key: str,
    expected: Any,
) -> None:
    observed = payload.get(key)
    if observed != expected:
        errors.append(f"{key} must be {expected!r}, got {observed!r}")


def validate_level(level: object) -> str:
    if not isinstance(level, str) or level not in ALLOWED_LEVELS:
        expected = ", ".join(ALLOWED_LEVELS)
        raise GridV2PinError(f"unsupported grid level {level!r}; expected one of {expected}")
    return level


def validate_cell_id(cell_id: object, *, level: str | None = None) -> str:
    """Validate canonical V2 Cell_ID syntax, level identity, and row/column bounds."""
    if not isinstance(cell_id, str):
        raise GridV2PinError("Cell_ID must be a string")
    match = _CELL_ID_RE.fullmatch(cell_id)
    if match is None:
        raise GridV2PinError(f"malformed V2 Cell_ID: {cell_id!r}")

    cell_level, row_text, column_text = match.groups()
    rows, columns = LEVEL_DIMENSIONS[cell_level]
    row = int(row_text)
    column = int(column_text)
    if row >= rows or column >= columns:
        raise GridV2PinError(f"Cell_ID out of range for {cell_level}: row={row} column={column}")

    if level is not None:
        selected_level = validate_level(level)
        if cell_level != selected_level:
            raise GridV2PinError(
                f"Cell_ID level {cell_level} does not match requested level {selected_level}"
            )
    return cell_id


def validate_pin_payload(
    payload: Mapping[str, Any],
    *,
    expected_consumer: str | None = None,
    required_level: str | None = None,
) -> list[str]:
    """Return validation errors; an empty list is the only compatible state."""
    errors: list[str] = []

    _expect_equal(errors, payload, "schema_version", PIN_SCHEMA_VERSION)
    _expect_equal(errors, payload, "geometry_authority", GEOMETRY_AUTHORITY)
    _expect_equal(errors, payload, "authority_repository", AUTHORITY_REPOSITORY)
    _expect_equal(errors, payload, "authority_commit", AUTHORITY_COMMIT)
    _expect_equal(errors, payload, "authority_manifest_path", AUTHORITY_MANIFEST_PATH)
    _expect_equal(errors, payload, "grid_id", GRID_ID)
    _expect_equal(errors, payload, "grid_version", GRID_VERSION)
    _expect_equal(errors, payload, "crs", CRS)
    _expect_equal(errors, payload, "grid_manifest_sha256", GRID_MANIFEST_SHA256)
    _expect_equal(errors, payload, "cell_schema_sha256", CELL_SCHEMA_SHA256)
    _expect_equal(errors, payload, "binding_schema_sha256", BINDING_SCHEMA_SHA256)
    _expect_equal(errors, payload, "binding_schema_version", BINDING_SCHEMA_VERSION)
    _expect_equal(errors, payload, "mask_schema_sha256", MASK_SCHEMA_SHA256)
    _expect_equal(errors, payload, "mask_schema_version", MASK_SCHEMA_VERSION)
    _expect_equal(errors, payload, "geometry_mode", "REFERENCE_ONLY")
    _expect_equal(errors, payload, "local_geometry_copy", False)
    _expect_equal(errors, payload, "v1_coexistence", "PRESERVE_UNCHANGED")
    _expect_equal(errors, payload, "compatibility_policy", "FAIL_CLOSED")

    consumer = payload.get("consumer")
    if consumer not in EXPECTED_CONSUMERS:
        errors.append(f"unknown V2 consumer: {consumer!r}")
    if expected_consumer is not None and consumer != expected_consumer:
        errors.append(f"consumer must be {expected_consumer!r}, got {consumer!r}")

    observed_levels = payload.get("allowed_levels")
    if observed_levels != list(ALLOWED_LEVELS):
        errors.append(f"allowed_levels must be {list(ALLOWED_LEVELS)!r}, got {observed_levels!r}")

    default_level = payload.get("default_level")
    expected_default = EXPECTED_DEFAULT_LEVELS.get(str(consumer))
    if expected_default is not None and default_level != expected_default:
        errors.append(
            f"default_level for {consumer} must be {expected_default}, got {default_level!r}"
        )

    if required_level is not None:
        try:
            required = validate_level(required_level)
        except GridV2PinError as exc:
            errors.append(str(exc))
        else:
            if not isinstance(observed_levels, list) or required not in observed_levels:
                errors.append(f"required level {required} is not enabled by this pin")

    for key in (
        "grid_manifest_sha256",
        "cell_schema_sha256",
        "binding_schema_sha256",
        "mask_schema_sha256",
    ):
        value = payload.get(key)
        if not isinstance(value, str) or not _HASH_RE.fullmatch(value):
            errors.append(f"{key} must be a lowercase SHA-256")

    blockers = payload.get("external_provider_blockers")
    expected_blockers = {
        "QA-D24-001": False,
        "QA-D24-003": False,
    }
    if not isinstance(blockers, list):
        errors.append("external_provider_blockers must be a list")
    else:
        observed_blockers = {}
        for row in blockers:
            if not isinstance(row, Mapping):
                errors.append("external_provider_blockers entries must be objects")
                continue
            blocker_id = row.get("id")
            affects = row.get("affects_grid_identity")
            if not isinstance(blocker_id, str) or not isinstance(affects, bool):
                errors.append("invalid external provider blocker entry")
                continue
            observed_blockers[blocker_id] = affects
        if observed_blockers != expected_blockers:
            errors.append(
                "external provider blockers must remain "
                f"{expected_blockers!r}, got {observed_blockers!r}"
            )

    return errors


def load_pin(
    path: str | Path,
    *,
    expected_consumer: str | None = None,
    required_level: str | None = None,
) -> GridV2Pin:
    """Load one pin and fail closed on any incompatibility."""
    pin_path = Path(path)
    try:
        payload = json.loads(pin_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GridV2PinError(f"cannot load V2 grid pin {pin_path}: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise GridV2PinError("V2 grid pin root must be an object")

    errors = validate_pin_payload(
        payload,
        expected_consumer=expected_consumer,
        required_level=required_level,
    )
    if errors:
        raise GridV2PinError("; ".join(errors))

    consumer = str(payload["consumer"])
    return GridV2Pin(
        consumer=consumer,
        default_level=str(payload["default_level"]),
        allowed_levels=tuple(str(x) for x in payload["allowed_levels"]),
        payload=payload,
    )


def grid_identity(
    pin: GridV2Pin,
    *,
    level: str | None = None,
    cell_id: str | None = None,
) -> dict[str, str]:
    """Return the immutable identity envelope to stamp on grid-aware outputs."""
    selected_level = pin.default_level if level is None else validate_level(level)
    if selected_level not in pin.allowed_levels:
        raise GridV2PinError(f"grid level {selected_level} is not permitted for {pin.consumer}")
    identity = {
        "Grid_ID": GRID_ID,
        "Grid_Version": GRID_VERSION,
        "Grid_Level": selected_level,
        "CRS": CRS,
        "Grid_Manifest_SHA256": GRID_MANIFEST_SHA256,
        "Cell_Schema_SHA256": CELL_SCHEMA_SHA256,
        "Binding_Schema_SHA256": BINDING_SCHEMA_SHA256,
        "Mask_Schema_SHA256": MASK_SCHEMA_SHA256,
        "Geometry_Authority": GEOMETRY_AUTHORITY,
        "Authority_Commit": AUTHORITY_COMMIT,
    }
    if cell_id is not None:
        identity["Cell_ID"] = validate_cell_id(cell_id, level=selected_level)
    return identity


def attach_grid_identity(
    payload: Mapping[str, Any],
    pin: GridV2Pin,
    *,
    level: str | None = None,
    cell_id: str | None = None,
) -> dict[str, Any]:
    """Copy a payload and attach one validated immutable Grid_Identity envelope."""
    output = dict(payload)
    output["Grid_Identity"] = grid_identity(
        pin,
        level=level,
        cell_id=cell_id,
    )
    return output


def build_grid_deep_link(
    pin: GridV2Pin,
    *,
    level: str | None = None,
    cell_id: str,
    base_path: str = "",
    as_of: str | None = None,
) -> str:
    """Build the canonical federation deep link for one validated V2 cell."""
    selected_level = pin.default_level if level is None else validate_level(level)
    if selected_level not in pin.allowed_levels:
        raise GridV2PinError(
            f"grid level {selected_level} is not permitted for {pin.consumer}"
        )
    validated_cell = validate_cell_id(cell_id, level=selected_level)
    prefix = base_path.rstrip("/")
    path = (
        f"{prefix}/grid/{GRID_ID}/{GRID_VERSION}/{selected_level}/{quote(validated_cell, safe=':')}"
    )
    if as_of is not None:
        if not isinstance(as_of, str) or not as_of.strip():
            raise GridV2PinError("as_of cannot be blank")
        path += "?as_of=" + quote(as_of, safe="")
    return path


def validate_pin_set(
    pin_paths: Mapping[str, str | Path],
) -> dict[str, GridV2Pin]:
    """Validate the complete six-consumer denominator against one authority."""
    supplied = set(pin_paths)
    if supplied != set(EXPECTED_CONSUMERS):
        missing = sorted(set(EXPECTED_CONSUMERS) - supplied)
        extra = sorted(supplied - set(EXPECTED_CONSUMERS))
        raise GridV2PinError(
            f"consumer pin denominator mismatch: missing={missing!r} extra={extra!r}"
        )

    validated = {}
    for consumer in sorted(EXPECTED_CONSUMERS):
        validated[consumer] = load_pin(
            pin_paths[consumer],
            expected_consumer=consumer,
        )

    identities = {
        (
            pin.payload["authority_commit"],
            pin.payload["grid_manifest_sha256"],
            pin.payload["cell_schema_sha256"],
            pin.payload["binding_schema_sha256"],
            pin.payload["mask_schema_sha256"],
        )
        for pin in validated.values()
    }
    if len(identities) != 1:
        raise GridV2PinError("consumer V2 pins do not share one authority identity")
    return validated
