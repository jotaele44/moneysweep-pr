"""Runtime parity tests for Spiderweb PR_GRID_GEOGRAPHIC_V2 RC1."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PIN_PATH = ROOT / "federation/spatial/pr_grid_geographic_v2.pin.json"
RUNTIME_PATH = ROOT / "federation/spatial/pr_grid_geographic_v2_runtime.py"
RUNTIME_SHA256 = "1e616e15ce5b22ac0623dcc2cc557a86c26a5eac9d4415b87d4cac71ec199956"
RUNTIME_AUTHORITY_COMMIT = "ef8404aa7a1954e88ae164155857961850d82a6a"


def _runtime():
    spec = importlib.util.spec_from_file_location("pr_grid_v2_runtime", RUNTIME_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_vendored_runtime_bytes_and_authority_pin_are_exact():
    pin = json.loads(PIN_PATH.read_text(encoding="utf-8"))
    assert hashlib.sha256(RUNTIME_PATH.read_bytes()).hexdigest() == RUNTIME_SHA256
    assert pin["runtime_contract_version"] == "pr-grid-v2-runtime/1.0"
    assert pin["runtime_authority_commit"] == RUNTIME_AUTHORITY_COMMIT
    assert pin["runtime_authority_path"] == (
        "federation/spatial/pr_grid_geographic_v2_runtime.py"
    )
    assert pin["runtime_module_sha256"] == RUNTIME_SHA256


def test_runtime_accepts_local_pin_and_emits_identity_and_deep_link():
    runtime = _runtime()
    pin = runtime.load_pin(PIN_PATH)
    runtime.validate_pin(pin)
    level = pin["default_level"]
    cell_id = f"PRG2:{level}:R000:C0000"
    identity = runtime.runtime_identity(pin, level=level, cell_id=cell_id)
    assert identity["Grid_ID"] == "PR_GRID_GEOGRAPHIC_V2"
    assert identity["Grid_Version"] == "2.0.0-rc1"
    assert identity["Grid_Level"] == level
    assert identity["Cell_ID"] == cell_id
    assert identity["Grid_Manifest_SHA256"] == pin["grid_manifest_sha256"]
    assert runtime.build_grid_deep_link(
        pin, level=level, cell_id=cell_id
    ) == f"/grid/PR_GRID_GEOGRAPHIC_V2/2.0.0-rc1/{level}/{cell_id}"


@pytest.mark.parametrize(
    ("key", "bad"),
    [
        ("grid_id", "PR_GRID_LOGICAL_V1"),
        ("grid_version", "2.0.0"),
        ("grid_manifest_sha256", "0" * 64),
        ("cell_schema_sha256", "0" * 64),
        ("binding_schema_sha256", "0" * 64),
        ("mask_schema_sha256", "0" * 64),
    ],
)
def test_identity_and_hash_mismatches_fail_closed(key, bad):
    runtime = _runtime()
    pin = runtime.load_pin(PIN_PATH)
    candidate = copy.deepcopy(pin)
    candidate[key] = bad
    with pytest.raises(runtime.GridV2RuntimeError):
        runtime.validate_pin(candidate)


def test_wrong_level_and_wrong_cell_id_fail_closed():
    runtime = _runtime()
    pin = runtime.load_pin(PIN_PATH)
    with pytest.raises(runtime.GridV2RuntimeError):
        runtime.validate_level(pin, "L4")
    with pytest.raises(runtime.GridV2RuntimeError):
        runtime.validate_cell_id(pin, "R0_C0", level=pin["default_level"])
    wrong_level = "L0" if pin["default_level"] != "L0" else "L1"
    with pytest.raises(runtime.GridV2RuntimeError):
        runtime.validate_cell_id(
            pin,
            f"PRG2:{wrong_level}:R000:C0000",
            level=pin["default_level"],
        )
