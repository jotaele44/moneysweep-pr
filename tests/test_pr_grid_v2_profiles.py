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
            "Migration_Provenance_Class": "RECOMPUTED_FROM_SOURCE_COORDINATE",
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
    assert profiles[0]["Grid_Deep_Link"].startswith("/grid/PR_GRID_GEOGRAPHIC_V2/2.0.0-rc1/")
    assert profiles[0]["Migration_Class"] == "RECOMPUTED_FROM_SOURCE_COORDINATE"
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


def _replace_binding(args, row, *, migration_class=None):
    _write(args["bindings_path"], row)
    raw = args["bindings_path"].read_bytes()
    receipt = json.loads(args["receipt_path"].read_text())
    receipt["Binding_Output_SHA256"] = hashlib.sha256(raw).hexdigest()
    receipt["Binding_Output_Bytes"] = len(raw)
    receipt["Binding_Row_Count"] = 1
    if migration_class is not None:
        receipt["Migration_Provenance_Class"] = migration_class
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
    _replace_binding(
        args,
        base,
        migration_class="RECOMPUTED_FROM_SOURCE_GEOMETRY",
    )

    profiles, receipt = build_profiles(**args)
    assert profiles[0]["Data_State"] == "HAS_RECORDS"
    assert profiles[0]["Record_Count"] == 1
    assert profiles[0]["Shared_Boundary_Record_Count"] == 0
    assert profiles[0]["Binding_Method_Counts"] == {method: 1}
    assert profiles[0]["Uncertainty_Class_Counts"] == {"EXACT": 1}
    assert profiles[0]["Exact_Record_Count"] == 1
    assert profiles[0]["Non_Exact_Record_Count"] == 0
    assert receipt["Migration_Class"] == "RECOMPUTED_FROM_SOURCE_GEOMETRY"
    assert receipt["Accepted_Binding_Methods"] == [
        "COVERS",
        "INTERSECTS_POSITIVE_AREA",
        "LINE_POSITIVE_LENGTH",
        "ADMINISTRATIVE_SET",
        "DERIVED_SET",
    ]


@pytest.mark.parametrize(
    ("method", "uncertainty", "geometry_state"),
    [
        (
            "ADMINISTRATIVE_SET",
            "ADMINISTRATIVE_ONLY",
            "VERIFIED_ADMINISTRATIVE_GEOMETRY",
        ),
        (
            "DERIVED_SET",
            "DERIVED",
            "VERIFIED_DERIVED_GEOMETRY",
        ),
    ],
)
def test_evidence_gated_set_bindings_enter_profiles(
    tmp_path, method, uncertainty, geometry_state
):
    args = _inputs(tmp_path)
    base = json.loads(args["bindings_path"].read_text())
    base.update(
        {
            "Binding_Method": method,
            "Uncertainty_Class": uncertainty,
            "Binding_State": "INTERIOR",
            "Overlap_Area_m2": 250000.0,
            "Cell_Coverage_Fraction": 0.25,
            "Geometry_State": geometry_state,
            "Confidence": None,
        }
    )
    _replace_binding(
        args,
        base,
        migration_class="RECOMPUTED_FROM_SOURCE_GEOMETRY",
    )

    profiles, receipt = build_profiles(**args)
    profile = profiles[0]
    assert profile["Data_State"] == "HAS_RECORDS"
    assert profile["Binding_Method_Counts"] == {method: 1}
    assert profile["Uncertainty_Class_Counts"] == {uncertainty: 1}
    assert profile["Exact_Record_Count"] == 0
    assert profile["Non_Exact_Record_Count"] == 1
    assert profile["Geometry_Included"] is False
    assert receipt["Migration_Class"] == "RECOMPUTED_FROM_SOURCE_GEOMETRY"
    assert receipt["Accepted_Set_Policies"][method]["Uncertainty_Class"] == uncertainty
    assert receipt["Accepted_Set_Policies"][method]["Geometry_State"] == geometry_state
    assert receipt["Accepted_Set_Policies"][method]["Confidence"] is None


@pytest.mark.parametrize(
    ("method", "uncertainty", "geometry_state", "confidence", "message"),
    [
        (
            "ADMINISTRATIVE_SET",
            "EXACT",
            "VERIFIED_ADMINISTRATIVE_GEOMETRY",
            None,
            "ADMINISTRATIVE_ONLY",
        ),
        (
            "ADMINISTRATIVE_SET",
            "ADMINISTRATIVE_ONLY",
            "VERIFIED_DERIVED_GEOMETRY",
            None,
            "VERIFIED_ADMINISTRATIVE_GEOMETRY",
        ),
        (
            "DERIVED_SET",
            "DERIVED",
            "VERIFIED_DERIVED_GEOMETRY",
            1.0,
            "Confidence=null",
        ),
        (
            "COVERS",
            "APPROXIMATE",
            None,
            None,
            "Uncertainty_Class=EXACT",
        ),
    ],
)
def test_unsupported_binding_policy_fails_closed(
    tmp_path, method, uncertainty, geometry_state, confidence, message
):
    args = _inputs(tmp_path)
    base = json.loads(args["bindings_path"].read_text())
    base.update(
        {
            "Binding_Method": method,
            "Uncertainty_Class": uncertainty,
            "Binding_State": "INTERIOR",
            "Overlap_Area_m2": 250000.0,
            "Cell_Coverage_Fraction": 0.25,
            "Geometry_State": geometry_state,
            "Confidence": confidence,
        }
    )
    _replace_binding(
        args,
        base,
        migration_class="RECOMPUTED_FROM_SOURCE_GEOMETRY",
    )
    with pytest.raises(ProfileError, match=message):
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
        (
            "ADMINISTRATIVE_SET",
            {
                "Uncertainty_Class": "ADMINISTRATIVE_ONLY",
                "Geometry_State": "VERIFIED_ADMINISTRATIVE_GEOMETRY",
                "Confidence": None,
                "Overlap_Area_m2": 0.0,
                "Cell_Coverage_Fraction": 0.0,
            },
            "positive-area",
        ),
    ],
)
def test_zero_measure_exact_geometry_binding_fails_closed(tmp_path, method, fields, message):
    args = _inputs(tmp_path)
    base = json.loads(args["bindings_path"].read_text())
    base["Binding_Method"] = method
    base["Binding_State"] = "INTERIOR"
    base.update(fields)
    _replace_binding(
        args,
        base,
        migration_class="RECOMPUTED_FROM_SOURCE_GEOMETRY",
    )

    with pytest.raises(ProfileError, match=message):
        build_profiles(**args)


def test_incremental_refresh_recomputes_old_and_new_cells(tmp_path):
    args = _inputs(tmp_path)
    full_profiles, _ = build_profiles(**args)
    previous_profiles = tmp_path / "previous-profiles.jsonl"
    previous_profiles.write_text(
        "".join(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in full_profiles),
        encoding="utf-8",
    )

    previous_bindings = tmp_path / "previous-bindings.jsonl"
    previous_bindings.write_bytes(args["bindings_path"].read_bytes())
    previous_receipt = tmp_path / "previous-receipt.json"
    previous_receipt.write_bytes(args["receipt_path"].read_bytes())

    original = json.loads(args["bindings_path"].read_text())
    moved = dict(original)
    moved["Cell_ID"] = "PRG2:" + LEVEL + ":R000:C0003"
    _replace_binding(args, moved)

    from pr_grid_v2_profiles import build_incremental_profiles

    profiles, receipt = build_incremental_profiles(
        pin_path=args["pin_path"],
        records_path=args["records_path"],
        bindings_path=args["bindings_path"],
        receipt_path=args["receipt_path"],
        previous_bindings_path=previous_bindings,
        previous_receipt_path=previous_receipt,
        previous_profiles_path=previous_profiles,
        coverage_path=args["coverage_path"],
        level=LEVEL,
        changed_record_ids=("record-a",),
    )

    assert receipt["Refresh_Mode"] == "INCREMENTAL"
    assert receipt["Output_Mode"] == "DELTA_UPSERT"
    assert receipt["Impact_Cell_Count"] == 2
    assert receipt["Impacted_Cell_IDs"] == sorted(
        [
            "PRG2:" + LEVEL + ":R000:C0000",
            "PRG2:" + LEVEL + ":R000:C0003",
        ]
    )
    assert receipt["Rollback_Target_SHA256"] == hashlib.sha256(
        previous_profiles.read_bytes()
    ).hexdigest()
    by_cell = {row["Cell_ID"]: row for row in profiles}
    assert by_cell["PRG2:" + LEVEL + ":R000:C0000"]["Data_State"] == "NO_DATA"
    assert by_cell["PRG2:" + LEVEL + ":R000:C0003"]["Data_State"] == "HAS_RECORDS"


def test_incremental_refresh_requires_declared_change(tmp_path):
    args = _inputs(tmp_path)
    from pr_grid_v2_profiles import ProfileError, compute_impacted_cells

    previous_bindings = tmp_path / "previous-bindings.jsonl"
    previous_bindings.write_bytes(args["bindings_path"].read_bytes())
    previous_receipt = tmp_path / "previous-receipt.json"
    previous_receipt.write_bytes(args["receipt_path"].read_bytes())

    with pytest.raises(ProfileError, match="requires changed"):
        compute_impacted_cells(
            pin_path=args["pin_path"],
            previous_bindings_path=previous_bindings,
            previous_receipt_path=previous_receipt,
            bindings_path=args["bindings_path"],
            receipt_path=args["receipt_path"],
            level=LEVEL,
        )
