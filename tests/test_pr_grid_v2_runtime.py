"""Runtime tests for the fail-closed PR_GRID_GEOGRAPHIC_V2 consumer contract."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from federation.pr_grid_v2 import (
    GridV2PinError,
    attach_grid_identity,
    grid_deep_link,
    grid_identity,
    load_grid_v2_pin,
    validate_grid_route,
)

ROOT = Path(__file__).resolve().parents[1]
PIN_PATH = ROOT / "federation/spatial/pr_grid_geographic_v2.pin.json"
EXPECTED_CONSUMER = "moneysweep-pr"
EXPECTED_LEVEL = "L1"


def _mutated_root(tmp_path: Path, key: str, value: object) -> Path:
    payload = json.loads(PIN_PATH.read_text(encoding="utf-8"))
    payload[key] = value
    target = tmp_path / "federation/spatial"
    target.mkdir(parents=True)
    (target / "pr_grid_geographic_v2.pin.json").write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
    )
    return tmp_path


def test_runtime_loads_exact_repo_pin():
    pin = load_grid_v2_pin(
        ROOT,
        expected_consumer=EXPECTED_CONSUMER,
        requested_level=EXPECTED_LEVEL,
    )
    assert pin.consumer == EXPECTED_CONSUMER
    assert pin.default_level == EXPECTED_LEVEL
    assert pin.geometry_mode == "REFERENCE_ONLY"
    assert pin.local_geometry_copy is False


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("grid_id", "WRONG_GRID"),
        ("grid_version", "9.9.9"),
        ("grid_manifest_sha256", "0" * 64),
        ("cell_schema_sha256", "1" * 64),
        ("binding_schema_sha256", "2" * 64),
        ("mask_schema_sha256", "3" * 64),
    ],
)
def test_identity_and_hash_drift_fail_closed(tmp_path, key, value):
    root = _mutated_root(tmp_path, key, value)
    with pytest.raises(GridV2PinError):
        load_grid_v2_pin(root, expected_consumer=EXPECTED_CONSUMER)


def test_unsupported_level_fails_closed():
    with pytest.raises(GridV2PinError):
        load_grid_v2_pin(
            ROOT,
            expected_consumer=EXPECTED_CONSUMER,
            requested_level="L9",
        )


def test_grid_identity_is_attached_without_overwriting_conflicts():
    pin = load_grid_v2_pin(ROOT, expected_consumer=EXPECTED_CONSUMER)
    identity = grid_identity(pin)
    assert identity["Grid_ID"] == "PR_GRID_GEOGRAPHIC_V2"
    assert identity["Grid_Version"] == "2.0.0-rc1"
    assert identity["Grid_Level"] == EXPECTED_LEVEL
    assert identity["Grid_Manifest_SHA256"].startswith("8902af18")

    payload = attach_grid_identity({"Record_Count": 0}, pin)
    assert payload["Record_Count"] == 0
    assert payload["Grid_ID"] == "PR_GRID_GEOGRAPHIC_V2"

    with pytest.raises(GridV2PinError):
        attach_grid_identity({"Grid_ID": "WRONG_GRID"}, pin)


def test_deep_link_and_route_are_version_and_level_safe():
    pin = load_grid_v2_pin(ROOT, expected_consumer=EXPECTED_CONSUMER)
    cell_id = f"PRG2:{EXPECTED_LEVEL}:R001:C0002"

    link = grid_deep_link(cell_id, pin)
    assert link == (
        f"/grid/PR_GRID_GEOGRAPHIC_V2/2.0.0-rc1/{EXPECTED_LEVEL}/"
        f"PRG2%3A{EXPECTED_LEVEL}%3AR001%3AC0002"
    )

    assert (
        validate_grid_route(
            grid_id=pin.grid_id,
            grid_version=pin.grid_version,
            level=EXPECTED_LEVEL,
            cell_id=cell_id,
            pin=pin,
        )
        == cell_id
    )

    with pytest.raises(GridV2PinError):
        validate_grid_route(
            grid_id=pin.grid_id,
            grid_version="2.0.0",
            level=EXPECTED_LEVEL,
            cell_id=cell_id,
            pin=pin,
        )

    wrong_level = "L3" if EXPECTED_LEVEL != "L3" else "L2"
    with pytest.raises(GridV2PinError):
        validate_grid_route(
            grid_id=pin.grid_id,
            grid_version=pin.grid_version,
            level=wrong_level,
            cell_id=cell_id,
            pin=pin,
        )
