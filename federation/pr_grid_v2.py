"""Fail-closed runtime contract for Spiderweb PR_GRID_GEOGRAPHIC_V2.

This module is intentionally geometry-free. Spiderweb remains the sole geometry
authority; consumers validate a content-addressed pin, expose grid identity, and
construct/validate federation deep links.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

PIN_RELATIVE_PATH = Path("federation/spatial/pr_grid_geographic_v2.pin.json")

EXPECTED_AUTHORITY_REPOSITORY = "jotaele44/spiderweb-pr"
EXPECTED_AUTHORITY_COMMIT = "0c66e13d14232c0d7cbcbc179b3655904777dc71"
EXPECTED_GRID_ID = "PR_GRID_GEOGRAPHIC_V2"
EXPECTED_GRID_VERSION = "2.0.0-rc1"
EXPECTED_CRS = "EPSG:6566"
EXPECTED_GRID_MANIFEST_SHA256 = "8902af188ad449955119016f5747fe2393c582d9ed552fb03bcaecd9ab510aa4"
EXPECTED_CELL_SCHEMA_SHA256 = "1c173aee4b21b9baa545b656735155f2236a87c436d467a12132ef53b2592f5d"
EXPECTED_BINDING_SCHEMA_SHA256 = "dabc461e47134b3b150be9aeb23b3d0097563493b33b3187538255e06b16a022"
EXPECTED_MASK_SCHEMA_SHA256 = "0b31b717d274b19686bf7f47edbabdaec31c86800f2ca7f1e73ffb663600978b"
EXPECTED_BINDING_SCHEMA_VERSION = "pr-grid-v2-binding/1.0"
EXPECTED_MASK_SCHEMA_VERSION = "pr-grid-v2-mask/1.0"
EXPECTED_ALLOWED_LEVELS = ("L0", "L1", "L2", "L3")
EXPECTED_GEOMETRY_MODE = "REFERENCE_ONLY"
EXPECTED_COMPATIBILITY_POLICY = "FAIL_CLOSED"

_CELL_ID_RE = re.compile(r"^PRG2:(L[0-3]):R[0-9]{3}:C[0-9]{4}$")


class GridV2PinError(RuntimeError):
    """Raised when the runtime V2 contract cannot be trusted."""


@dataclass(frozen=True)
class GridV2Pin:
    consumer: str
    authority_repository: str
    authority_commit: str
    grid_id: str
    grid_version: str
    crs: str
    grid_manifest_sha256: str
    cell_schema_sha256: str
    binding_schema_sha256: str
    binding_schema_version: str
    mask_schema_sha256: str
    mask_schema_version: str
    default_level: str
    allowed_levels: tuple[str, ...]
    geometry_mode: str
    local_geometry_copy: bool
    v1_coexistence: str
    compatibility_policy: str

    def resolve_level(self, level: str | None = None) -> str:
        resolved = self.default_level if level is None else str(level)
        if resolved not in self.allowed_levels:
            raise GridV2PinError(
                f"unsupported PR grid V2 level {resolved!r}; "
                f"allowed={list(self.allowed_levels)!r}"
            )
        return resolved


def _require_equal(payload: dict[str, Any], key: str, expected: Any) -> None:
    actual = payload.get(key)
    if actual != expected:
        raise GridV2PinError(
            f"PR grid V2 pin mismatch for {key}: expected {expected!r}, got {actual!r}"
        )


def _load_payload(repo_root: str | Path) -> dict[str, Any]:
    path = Path(repo_root) / PIN_RELATIVE_PATH
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise GridV2PinError(f"cannot read PR grid V2 pin: {path}") from exc
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise GridV2PinError(f"invalid PR grid V2 pin JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise GridV2PinError("PR grid V2 pin must be a JSON object")
    return payload


def load_grid_v2_pin(
    repo_root: str | Path,
    *,
    expected_consumer: str | None = None,
    requested_level: str | None = None,
) -> GridV2Pin:
    """Load and strictly validate the repository's canonical V2 consumer pin."""

    payload = _load_payload(repo_root)

    _require_equal(payload, "schema_version", "pr_grid_geographic_v2_consumer_pin/1.0")
    _require_equal(payload, "geometry_authority", "spiderweb-pr")
    _require_equal(payload, "authority_repository", EXPECTED_AUTHORITY_REPOSITORY)
    _require_equal(payload, "authority_commit", EXPECTED_AUTHORITY_COMMIT)
    _require_equal(payload, "grid_id", EXPECTED_GRID_ID)
    _require_equal(payload, "grid_version", EXPECTED_GRID_VERSION)
    _require_equal(payload, "crs", EXPECTED_CRS)
    _require_equal(payload, "grid_manifest_sha256", EXPECTED_GRID_MANIFEST_SHA256)
    _require_equal(payload, "cell_schema_sha256", EXPECTED_CELL_SCHEMA_SHA256)
    _require_equal(payload, "binding_schema_sha256", EXPECTED_BINDING_SCHEMA_SHA256)
    _require_equal(payload, "binding_schema_version", EXPECTED_BINDING_SCHEMA_VERSION)
    _require_equal(payload, "mask_schema_sha256", EXPECTED_MASK_SCHEMA_SHA256)
    _require_equal(payload, "mask_schema_version", EXPECTED_MASK_SCHEMA_VERSION)
    _require_equal(payload, "geometry_mode", EXPECTED_GEOMETRY_MODE)
    _require_equal(payload, "local_geometry_copy", False)
    _require_equal(payload, "v1_coexistence", "PRESERVE_UNCHANGED")
    _require_equal(payload, "compatibility_policy", EXPECTED_COMPATIBILITY_POLICY)

    consumer = payload.get("consumer")
    if not isinstance(consumer, str) or not consumer:
        raise GridV2PinError("PR grid V2 pin has no valid consumer")
    if expected_consumer is not None and consumer != expected_consumer:
        raise GridV2PinError(
            f"PR grid V2 consumer mismatch: expected {expected_consumer!r}, got {consumer!r}"
        )

    allowed = payload.get("allowed_levels")
    if allowed != list(EXPECTED_ALLOWED_LEVELS):
        raise GridV2PinError(
            "PR grid V2 allowed_levels mismatch: "
            f"expected {list(EXPECTED_ALLOWED_LEVELS)!r}, got {allowed!r}"
        )
    default_level = payload.get("default_level")
    if default_level not in EXPECTED_ALLOWED_LEVELS:
        raise GridV2PinError(f"invalid PR grid V2 default_level: {default_level!r}")

    blockers = payload.get("external_provider_blockers")
    blocker_map = {}
    if isinstance(blockers, list):
        for row in blockers:
            if isinstance(row, dict) and isinstance(row.get("id"), str):
                blocker_map[row["id"]] = row.get("affects_grid_identity")
    if blocker_map != {"QA-D24-001": False, "QA-D24-003": False}:
        raise GridV2PinError(
            "external provider blocker semantics changed; grid identity must fail closed"
        )

    pin = GridV2Pin(
        consumer=consumer,
        authority_repository=payload["authority_repository"],
        authority_commit=payload["authority_commit"],
        grid_id=payload["grid_id"],
        grid_version=payload["grid_version"],
        crs=payload["crs"],
        grid_manifest_sha256=payload["grid_manifest_sha256"],
        cell_schema_sha256=payload["cell_schema_sha256"],
        binding_schema_sha256=payload["binding_schema_sha256"],
        binding_schema_version=payload["binding_schema_version"],
        mask_schema_sha256=payload["mask_schema_sha256"],
        mask_schema_version=payload["mask_schema_version"],
        default_level=default_level,
        allowed_levels=tuple(allowed),
        geometry_mode=payload["geometry_mode"],
        local_geometry_copy=payload["local_geometry_copy"],
        v1_coexistence=payload["v1_coexistence"],
        compatibility_policy=payload["compatibility_policy"],
    )
    pin.resolve_level(requested_level)
    return pin


def validate_cell_id(
    cell_id: str,
    pin: GridV2Pin,
    *,
    level: str | None = None,
) -> str:
    """Validate V2 Cell_ID syntax and level coherence without deriving geometry."""

    match = _CELL_ID_RE.fullmatch(str(cell_id))
    if not match:
        raise GridV2PinError(f"invalid PR grid V2 Cell_ID: {cell_id!r}")
    cell_level = match.group(1)
    expected_level = pin.resolve_level(level)
    if cell_level != expected_level:
        raise GridV2PinError(
            f"Cell_ID level mismatch: route/profile={expected_level}, cell={cell_level}"
        )
    return str(cell_id)


def grid_identity(pin: GridV2Pin, *, level: str | None = None) -> dict[str, Any]:
    """Canonical identity block required on V2 Cell_Profile/API payloads."""

    resolved = pin.resolve_level(level)
    return {
        "Grid_ID": pin.grid_id,
        "Grid_Version": pin.grid_version,
        "Grid_Level": resolved,
        "CRS": pin.crs,
        "Grid_Manifest_SHA256": pin.grid_manifest_sha256,
        "Cell_Schema_SHA256": pin.cell_schema_sha256,
        "Binding_Schema_SHA256": pin.binding_schema_sha256,
        "Binding_Schema_Version": pin.binding_schema_version,
        "Mask_Schema_SHA256": pin.mask_schema_sha256,
        "Mask_Schema_Version": pin.mask_schema_version,
        "Geometry_Authority": "spiderweb-pr",
        "Geometry_Mode": pin.geometry_mode,
    }


def attach_grid_identity(
    payload: dict[str, Any],
    pin: GridV2Pin,
    *,
    level: str | None = None,
) -> dict[str, Any]:
    """Return a copy with exact V2 identity, refusing conflicting pre-existing keys."""

    result = dict(payload)
    identity = grid_identity(pin, level=level)
    for key, value in identity.items():
        if key in result and result[key] != value:
            raise GridV2PinError(
                f"payload conflicts with canonical PR grid V2 identity at {key}"
            )
        result[key] = value
    return result


def validate_grid_route(
    *,
    grid_id: str,
    grid_version: str,
    level: str,
    cell_id: str,
    pin: GridV2Pin,
) -> str:
    """Fail closed on cross-repo route identity/version/level/Cell_ID drift."""

    if grid_id != pin.grid_id:
        raise GridV2PinError(f"wrong Grid_ID in route: {grid_id!r}")
    if grid_version != pin.grid_version:
        raise GridV2PinError(f"wrong Grid_Version in route: {grid_version!r}")
    pin.resolve_level(level)
    return validate_cell_id(cell_id, pin, level=level)


def grid_deep_link(
    cell_id: str,
    pin: GridV2Pin,
    *,
    level: str | None = None,
    prefix: str = "",
) -> str:
    """Build the canonical federation grid route.

    Cell_ID is percent-encoded as one path segment so the colon-bearing canonical
    identifier survives URL transport unchanged after decoding.
    """

    resolved = pin.resolve_level(level)
    validate_cell_id(cell_id, pin, level=resolved)
    base = prefix.rstrip("/")
    return (
        f"{base}/grid/{quote(pin.grid_id, safe='')}/"
        f"{quote(pin.grid_version, safe='')}/{resolved}/"
        f"{quote(cell_id, safe='')}"
    )
