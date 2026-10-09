"""Fail-closed runtime contract for PR_GRID_GEOGRAPHIC_V2 RC1.

This module is dependency-free by design so federation consumers can vendor it
byte-identically. Spiderweb is the authority for these runtime semantics.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping

GRID_ID = "PR_GRID_GEOGRAPHIC_V2"
GRID_VERSION = "2.0.0-rc1"
CRS = "EPSG:6566"
AUTHORITY_REPOSITORY = "jotaele44/spiderweb-pr"
AUTHORITY_COMMIT = "0c66e13d14232c0d7cbcbc179b3655904777dc71"
GRID_MANIFEST_SHA256 = "8902af188ad449955119016f5747fe2393c582d9ed552fb03bcaecd9ab510aa4"
CELL_SCHEMA_SHA256 = "1c173aee4b21b9baa545b656735155f2236a87c436d467a12132ef53b2592f5d"
BINDING_SCHEMA_SHA256 = "dabc461e47134b3b150be9aeb23b3d0097563493b33b3187538255e06b16a022"
MASK_SCHEMA_SHA256 = "0b31b717d274b19686bf7f47edbabdaec31c86800f2ca7f1e73ffb663600978b"
ALLOWED_LEVELS = ("L0", "L1", "L2", "L3")
_CELL_ID = re.compile(r"^PRG2:(L[0-3]):R([0-9]{3}):C([0-9]{4})$")


class GridV2RuntimeError(RuntimeError):
    """Raised when a runtime pin or request violates the frozen V2 contract."""


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_pin(path: str | Path) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception as exc:
        raise GridV2RuntimeError(f"cannot load grid V2 pin: {exc}") from exc
    if not isinstance(value, dict):
        raise GridV2RuntimeError("grid V2 pin must be a JSON object")
    return value


def _require(pin: Mapping[str, Any], key: str, expected: Any) -> None:
    actual = pin.get(key)
    if actual != expected:
        raise GridV2RuntimeError(
            f"{key} mismatch: expected {expected!r}, got {actual!r}"
        )


def validate_pin(pin: Mapping[str, Any]) -> None:
    _require(pin, "geometry_authority", "spiderweb-pr")
    _require(pin, "authority_repository", AUTHORITY_REPOSITORY)
    _require(pin, "authority_commit", AUTHORITY_COMMIT)
    _require(pin, "grid_id", GRID_ID)
    _require(pin, "grid_version", GRID_VERSION)
    _require(pin, "crs", CRS)
    _require(pin, "grid_manifest_sha256", GRID_MANIFEST_SHA256)
    _require(pin, "cell_schema_sha256", CELL_SCHEMA_SHA256)
    _require(pin, "binding_schema_sha256", BINDING_SCHEMA_SHA256)
    _require(pin, "mask_schema_sha256", MASK_SCHEMA_SHA256)
    _require(pin, "geometry_mode", "REFERENCE_ONLY")
    _require(pin, "local_geometry_copy", False)
    _require(pin, "v1_coexistence", "PRESERVE_UNCHANGED")
    _require(pin, "compatibility_policy", "FAIL_CLOSED")

    allowed = tuple(pin.get("allowed_levels") or ())
    if allowed != ALLOWED_LEVELS:
        raise GridV2RuntimeError(
            f"allowed_levels mismatch: expected {ALLOWED_LEVELS!r}, got {allowed!r}"
        )
    default = pin.get("default_level")
    if default not in ALLOWED_LEVELS:
        raise GridV2RuntimeError(f"unsupported default_level: {default!r}")


def validate_level(pin: Mapping[str, Any], level: str) -> str:
    validate_pin(pin)
    if level not in ALLOWED_LEVELS:
        raise GridV2RuntimeError(f"unsupported grid level: {level!r}")
    if level not in tuple(pin["allowed_levels"]):
        raise GridV2RuntimeError(f"level not permitted by consumer pin: {level!r}")
    return level


def validate_cell_id(pin: Mapping[str, Any], cell_id: str, *, level: str | None = None) -> str:
    validate_pin(pin)
    match = _CELL_ID.fullmatch(cell_id)
    if not match:
        raise GridV2RuntimeError(f"malformed V2 Cell_ID: {cell_id!r}")
    cell_level = match.group(1)
    if level is not None:
        validate_level(pin, level)
        if cell_level != level:
            raise GridV2RuntimeError(
                f"Cell_ID level {cell_level!r} does not match requested level {level!r}"
            )
    return cell_id


def runtime_identity(pin: Mapping[str, Any], *, level: str, cell_id: str | None = None) -> dict[str, Any]:
    validate_level(pin, level)
    if cell_id is not None:
        validate_cell_id(pin, cell_id, level=level)
    return {
        "Grid_ID": GRID_ID,
        "Grid_Version": GRID_VERSION,
        "Grid_Level": level,
        "Cell_ID": cell_id,
        "CRS": CRS,
        "Grid_Manifest_SHA256": GRID_MANIFEST_SHA256,
        "Cell_Schema_SHA256": CELL_SCHEMA_SHA256,
        "Binding_Schema_SHA256": BINDING_SCHEMA_SHA256,
        "Mask_Schema_SHA256": MASK_SCHEMA_SHA256,
        "Geometry_Authority": "spiderweb-pr",
    }


def attach_runtime_identity(
    payload: Mapping[str, Any],
    pin: Mapping[str, Any],
    *,
    level: str,
    cell_id: str | None = None,
) -> dict[str, Any]:
    out = dict(payload)
    out["Grid_Identity"] = runtime_identity(pin, level=level, cell_id=cell_id)
    return out


def build_grid_deep_link(
    pin: Mapping[str, Any],
    *,
    level: str,
    cell_id: str,
    base_path: str = "",
    as_of: str | None = None,
) -> str:
    validate_cell_id(pin, cell_id, level=level)
    prefix = base_path.rstrip("/")
    path = f"{prefix}/grid/{GRID_ID}/{GRID_VERSION}/{level}/{cell_id}"
    if as_of is not None:
        if not str(as_of).strip():
            raise GridV2RuntimeError("as_of cannot be blank")
        path += f"?as_of={as_of}"
    return path
