"""Regression gates for federation record-cell binding v0.2."""
from __future__ import annotations
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = json.loads((ROOT / "federation/spatial/registry_version.json").read_text())
GEOMETRY = json.loads((ROOT / "federation/spatial/geometry_manifest.json").read_text())
SCHEMA = json.loads((ROOT / "federation/spatial/record_cell_binding.v0.2.schema.json").read_text())

def test_provisional_transform_requires_cell_set_and_forbids_exact_cell_claims():
    policy = REGISTRY["uncertainty_policy"]
    assert REGISTRY["certification_state"] == "PROVISIONAL"
    assert REGISTRY["binding_schema_version"] == "spiderweb.record_cell_binding.v0.2"
    assert policy["exact_cell_claims_permitted"] is False
    assert policy["cell_set_required"] is True
    assert policy["identity_default"] == "CANDIDATE_NOT_IDENTITY"
    assert policy["radius_semantics"] == "CONSERVATIVE_DISCOVERY_ENVELOPE_NOT_CONFIDENCE_INTERVAL"
    assert policy["independent_validation_state"] == "FAIL_KILL_CRITERIA"

def test_geometry_snapshot_matches_authority_and_stays_provisional():
    assert GEOMETRY["authority"] == "spiderweb-pr"
    assert GEOMETRY["certification_state"] == "PROVISIONAL"
    assert GEOMETRY["sha256"] == "5a84abe39eb80bde21c95698002097cb6ea8fda3c951c71db5c795b02538a422"

def test_schema_negative_gate_for_provisional_exact_cell_leakage():
    conditional = SCHEMA["allOf"][1]["then"]
    assert conditional["properties"]["Cell_ID"] == {"type": "null"}
    assert conditional["properties"]["Resolution_State"]["const"] == "PROVISIONAL_UNCERTAINTY_CELL_SET"
    assert conditional["properties"]["Uncertainty_Radius_Km"]["exclusiveMinimum"] == 0
    assert SCHEMA["properties"]["Identity_Default"]["const"] == "CANDIDATE_NOT_IDENTITY"

def test_schema_preserves_full_candidate_set_contract():
    members = SCHEMA["properties"]["Member_Cell_IDs"]
    assert members["minItems"] == 1
    assert members["uniqueItems"] is True
    assert "Cell_Set_SHA256" in SCHEMA["properties"]
    assert "Anchor_Cell_ID" in SCHEMA["properties"]
