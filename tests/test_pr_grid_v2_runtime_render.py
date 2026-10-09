"""Certification tests for the rendered PR grid V2 runtime contract."""

from __future__ import annotations

import json
import runpy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_PATH = ROOT / "federation/spatial/pr_grid_v2_runtime.py"
PIN_PATH = ROOT / "federation/spatial/pr_grid_geographic_v2.pin.json"
RUNTIME = runpy.run_path(str(RUNTIME_PATH))

GridV2PinError = RUNTIME["GridV2PinError"]
load_pin = RUNTIME["load_pin"]
grid_identity = RUNTIME["grid_identity"]
attach_grid_identity = RUNTIME["attach_grid_identity"]
build_grid_deep_link = RUNTIME["build_grid_deep_link"]
validate_cell_id = RUNTIME["validate_cell_id"]

EXPECTED_CONSUMER = "moneysweep-pr"
EXPECTED_LEVEL = "L1"


def _write_mutated_pin(tmp_path: Path, field: str, value: object) -> Path:
    payload = json.loads(PIN_PATH.read_text(encoding="utf-8"))
    payload[field] = value
    path = tmp_path / "pin.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_real_pin_loads_and_exposes_exact_grid_identity():
    pin = load_pin(
        PIN_PATH,
        expected_consumer=EXPECTED_CONSUMER,
        required_level=EXPECTED_LEVEL,
    )
    identity = grid_identity(pin)
    assert identity["Grid_ID"] == "PR_GRID_GEOGRAPHIC_V2"
    assert identity["Grid_Version"] == "2.0.0-rc1"
    assert identity["Grid_Level"] == EXPECTED_LEVEL
    assert identity["CRS"] == "EPSG:6566"
    assert identity["Geometry_Authority"] == "spiderweb-pr"
    assert identity["Authority_Commit"] == "0c66e13d14232c0d7cbcbc179b3655904777dc71"


@pytest.mark.parametrize(
    ("field", "bad_value"),
    [
        ("grid_id", "PR_GRID_LOGICAL_V1"),
        ("grid_version", "2.0.0"),
        ("grid_manifest_sha256", "0" * 64),
        ("cell_schema_sha256", "1" * 64),
        ("binding_schema_sha256", "2" * 64),
        ("mask_schema_sha256", "3" * 64),
    ],
)
def test_identity_or_schema_drift_fails_closed(tmp_path, field, bad_value):
    path = _write_mutated_pin(tmp_path, field, bad_value)
    with pytest.raises(GridV2PinError):
        load_pin(path, expected_consumer=EXPECTED_CONSUMER)


def test_unsupported_level_fails_closed():
    with pytest.raises(GridV2PinError, match="unsupported grid level"):
        load_pin(
            PIN_PATH,
            expected_consumer=EXPECTED_CONSUMER,
            required_level="L4",
        )


def test_cell_id_bounds_and_level_are_enforced():
    pin = load_pin(PIN_PATH, expected_consumer=EXPECTED_CONSUMER)
    good = f"PRG2:{EXPECTED_LEVEL}:R000:C0000"
    assert validate_cell_id(good, level=EXPECTED_LEVEL) == good

    wrong_level = "L3" if EXPECTED_LEVEL != "L3" else "L2"
    with pytest.raises(GridV2PinError):
        validate_cell_id(good, level=wrong_level)

    with pytest.raises(GridV2PinError):
        validate_cell_id(f"PRG2:{EXPECTED_LEVEL}:R999:C9999")


def test_cell_profile_identity_and_deep_link_are_canonical():
    pin = load_pin(PIN_PATH, expected_consumer=EXPECTED_CONSUMER)
    cell_id = f"PRG2:{EXPECTED_LEVEL}:R000:C0000"
    stamped = attach_grid_identity(
        {"Record_Count": 0, "Data_State": "ZERO_RECORDS"},
        pin,
        level=EXPECTED_LEVEL,
        cell_id=cell_id,
    )
    assert stamped["Data_State"] == "ZERO_RECORDS"
    assert stamped["Grid_Identity"]["Cell_ID"] == cell_id
    assert stamped["Grid_Identity"]["Grid_Level"] == EXPECTED_LEVEL

    link = build_grid_deep_link(
        pin,
        level=EXPECTED_LEVEL,
        cell_id=cell_id,
    )
    assert link == (
        f"/grid/PR_GRID_GEOGRAPHIC_V2/2.0.0-rc1/"
        f"{EXPECTED_LEVEL}/{cell_id}"
    )
