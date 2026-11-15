"""Consumer smoke tests for the shared PR grid V2 runtime."""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "federation/spatial"))

import pr_grid_v2_runtime as grid  # noqa: E402

PIN_PATH = ROOT / "federation/spatial/pr_grid_geographic_v2.pin.json"


def test_local_pin_loads_fail_closed_runtime():
    pin = grid.load_pin(
        PIN_PATH,
        expected_consumer="moneysweep-pr",
        required_level="L1",
    )
    assert pin.consumer == "moneysweep-pr"
    assert pin.default_level == "L1"
    identity = grid.grid_identity(pin)
    assert identity["Grid_ID"] == "PR_GRID_GEOGRAPHIC_V2"
    assert identity["Grid_Version"] == "2.0.0-rc1"
    assert identity["Grid_Level"] == "L1"
    assert identity["Grid_Manifest_SHA256"] == grid.GRID_MANIFEST_SHA256


def test_exact_cell_identity_and_deep_link():
    pin = grid.load_pin(PIN_PATH, expected_consumer="moneysweep-pr")
    sample = "PRG2:L1:R000:C0000"
    stamped = grid.attach_grid_identity(
        {"Record_Count": 0, "Data_State": "ZERO_RECORDS"},
        pin,
        level="L1",
        cell_id=sample,
    )
    assert stamped["Data_State"] == "ZERO_RECORDS"
    assert stamped["Grid_Identity"]["Cell_ID"] == sample
    link = grid.build_grid_deep_link(
        pin,
        level="L1",
        cell_id=sample,
        base_path="",
    )
    assert link == "/grid/PR_GRID_GEOGRAPHIC_V2/2.0.0-rc1/L1/" + sample


def test_wrong_manifest_hash_fails_closed(tmp_path):
    payload = json.loads(PIN_PATH.read_text(encoding="utf-8"))
    payload = copy.deepcopy(payload)
    payload["grid_manifest_sha256"] = "0" * 64
    bad = tmp_path / "bad-pin.json"
    bad.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(grid.GridV2PinError, match="grid_manifest_sha256"):
        grid.load_pin(bad, expected_consumer="moneysweep-pr")


def test_unsupported_level_and_noncanonical_cell_fail_closed():
    with pytest.raises(grid.GridV2PinError):
        grid.validate_level("L4")
    with pytest.raises(grid.GridV2PinError):
        grid.validate_cell_id("R0_C0")
