"""Shared consumer fixture: authoritative receipts and NO_DATA / ZERO_RECORDS."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "federation/spatial"))
import pr_grid_v2_runtime as grid  # noqa: E402
from pr_grid_v2_profiles import ProfileError, build_profiles  # noqa: E402

PIN_PATH = ROOT / "federation/spatial/pr_grid_geographic_v2.pin.json"
PIN = grid.load_pin(PIN_PATH)
LEVEL = PIN.default_level


def _write(path, data):
    path.write_text(json.dumps(data) + "\n", encoding="utf-8")
    return path


def _inputs(tmp_path):
    prefix = "PRG2:" + LEVEL + ":R000:C"
    a, b, c = (prefix + x for x in ("0000", "0001", "0002"))
    bindings = _write(
        tmp_path / "bindings.jsonl",
        {
            "Grid_ID": grid.GRID_ID,
            "Grid_Version": grid.GRID_VERSION,
            "Grid_Level": LEVEL,
            "Cell_ID": a,
            "Repository": PIN.consumer,
            "Record_ID": "record-a",
            "Binding_Method": "COVERS",
            "Uncertainty_Class": "EXACT",
            "Binding_State": "EDGE_SHARED",
        },
    )
    raw = bindings.read_bytes()
    receipt = _write(
        tmp_path / "receipt.json",
        {
            "Grid_ID": grid.GRID_ID,
            "Grid_Version": grid.GRID_VERSION,
            "Grid_Manifest_SHA256": grid.GRID_MANIFEST_SHA256,
            "Binding_Schema_Version": grid.BINDING_SCHEMA_VERSION,
            "Binding_Output_SHA256": hashlib.sha256(raw).hexdigest(),
            "Binding_Output_Bytes": len(raw),
            "Binding_Row_Count": 1,
        },
    )
    records = _write(
        tmp_path / "records.jsonl",
        {"Repository": PIN.consumer, "Record_ID": "record-a", "Category": "observations"},
    )
    coverage = _write(
        tmp_path / "coverage.json",
        {
            "Repository": PIN.consumer,
            "Grid_ID": grid.GRID_ID,
            "Grid_Version": grid.GRID_VERSION,
            "Grid_Level": LEVEL,
            "Grid_Manifest_SHA256": grid.GRID_MANIFEST_SHA256,
            "Coverage_Manifest_State": "VERIFIED",
            "Coverage_Evidence_SHA256": "a" * 64,
            "Coverage_Cells": [b],
        },
    )
    return {
        "pin_path": PIN_PATH,
        "records_path": records,
        "bindings_path": bindings,
        "receipt_path": receipt,
        "coverage_path": coverage,
        "level": LEVEL,
        "requested_cells": (c,),
    }


def test_domain_profile_preserves_evidence_states(tmp_path):
    args = _inputs(tmp_path)
    profiles, receipt = build_profiles(**args)
    assert [p["Data_State"] for p in profiles] == ["HAS_RECORDS", "ZERO_RECORDS", "NO_DATA"]
    assert profiles[0]["Profile_Type"]
    assert profiles[0]["Shared_Boundary_Record_Count"] == 1
    assert all(p["Geometry_Included"] is False for p in profiles)
    assert all(
        p["Grid_Identity"]["Grid_Manifest_SHA256"] == grid.GRID_MANIFEST_SHA256 for p in profiles
    )
    assert receipt["Profile_Count"] == 3


def test_corrupt_spiderweb_receipt_fails_closed(tmp_path):
    args = _inputs(tmp_path)
    row = json.loads(args["receipt_path"].read_text())
    row["Binding_Output_SHA256"] = "0" * 64
    _write(args["receipt_path"], row)
    with pytest.raises(ProfileError, match="Binding_Output_SHA256"):
        build_profiles(**args)


def test_without_coverage_empty_cells_mean_no_data(tmp_path):
    args = _inputs(tmp_path)
    args["coverage_path"] = None
    profiles, _ = build_profiles(**args)
    assert profiles[-1]["Data_State"] == "NO_DATA"
    assert all(p["Data_State"] != "ZERO_RECORDS" for p in profiles)


def _replace_binding(args, row):
    _write(args["bindings_path"], row)
    raw = args["bindings_path"].read_bytes()
    receipt = json.loads(args["receipt_path"].read_text())
    receipt["Binding_Output_SHA256"] = hashlib.sha256(raw).hexdigest()
    receipt["Binding_Output_Bytes"] = len(raw)
    receipt["Binding_Row_Count"] = 1
    _write(args["receipt_path"], receipt)


@pytest.mark.parametrize(
    ("method", "measure_fields"),
    [
        (
            "INTERSECTS_POSITIVE_AREA",
            {"Overlap_Area_m2": 250000.0, "Cell_Coverage_Fraction": 0.25},
        ),
        (
            "LINE_POSITIVE_LENGTH",
            {"Length_In_Cell_m": 500.0},
        ),
    ],
)
def test_exact_geometry_bindings_enter_profiles(tmp_path, method, measure_fields):
    args = _inputs(tmp_path)
    base = json.loads(args["bindings_path"].read_text())
    base["Binding_Method"] = method
    base["Binding_State"] = "INTERIOR"
    base.update(measure_fields)
    _replace_binding(args, base)

    profiles, receipt = build_profiles(**args)
    assert profiles[0]["Data_State"] == "HAS_RECORDS"
    assert profiles[0]["Record_Count"] == 1
    assert profiles[0]["Shared_Boundary_Record_Count"] == 0
    assert receipt["Migration_Class"] == "SPIDERWEB_CERTIFIED_EXACT_BINDINGS"
    assert receipt["Accepted_Binding_Methods"] == [
        "COVERS",
        "INTERSECTS_POSITIVE_AREA",
        "LINE_POSITIVE_LENGTH",
    ]


@pytest.mark.parametrize(
    ("method", "uncertainty"),
    [
        ("ADMINISTRATIVE_SET", "ADMINISTRATIVE_ONLY"),
        ("DERIVED_SET", "DERIVED"),
    ],
)
def test_non_exact_set_bindings_cannot_enter_exact_profiles(tmp_path, method, uncertainty):
    args = _inputs(tmp_path)
    base = json.loads(args["bindings_path"].read_text())
    base["Binding_Method"] = method
    base["Uncertainty_Class"] = uncertainty
    base["Binding_State"] = "INTERIOR"
    _replace_binding(args, base)

    with pytest.raises(ProfileError, match="non-exact"):
        build_profiles(**args)


@pytest.mark.parametrize(
    ("method", "fields", "message"),
    [
        (
            "INTERSECTS_POSITIVE_AREA",
            {"Overlap_Area_m2": 0.0, "Cell_Coverage_Fraction": 0.0},
            "positive-area",
        ),
        (
            "LINE_POSITIVE_LENGTH",
            {"Length_In_Cell_m": 0.0},
            "positive-length",
        ),
    ],
)
def test_zero_measure_exact_geometry_binding_fails_closed(tmp_path, method, fields, message):
    args = _inputs(tmp_path)
    base = json.loads(args["bindings_path"].read_text())
    base["Binding_Method"] = method
    base["Binding_State"] = "INTERIOR"
    base.update(fields)
    _replace_binding(args, base)

    with pytest.raises(ProfileError, match=message):
        build_profiles(**args)
