"""Shared strict exporter fixture for Spiderweb source-coordinate binding."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "federation/spatial/export_pr_grid_v2_exact_observations.py"
SPEC = importlib.util.spec_from_file_location("grid_v2_source_export", SCRIPT)
assert SPEC and SPEC.loader
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)


def _row(
    observation_id: str,
    *,
    exact: bool = True,
    synthetic: bool = False,
    location: dict | None = None,
):
    attributes = {}
    if exact:
        attributes["grid_v2_coordinate_evidence_state"] = mod.EVIDENCE_STATE
    return {
        "observation_id": observation_id,
        "source_id": "src_" + "1" * 32,
        "observation_type": "test_observation",
        "observed_at": "2026-10-20T12:00:00Z",
        "location": location or {"lat": 18.35, "lon": -66.0},
        "attributes": attributes,
        "confidence": 1.0,
        "lineage": {
            "producer_script": "fixture",
            "producer_phase": "test",
            "source_inputs": ["fixture"],
        },
        "synthetic": synthetic,
        "created_at": "2026-10-20T12:00:00Z",
        "extracted_at": "2026-10-20T12:00:00Z",
    }


def test_only_explicit_exact_observations_are_admitted():
    rows = [
        _row("obs_" + "a" * 32),
        _row("obs_" + "b" * 32, exact=False),
        _row("obs_" + "c" * 32, synthetic=True),
    ]
    sources, records, excluded = mod.project_observations(
        rows,
        repository="skywatcher-pr",
    )
    assert len(sources) == 1
    assert len(records) == 1
    assert sources[0] == {
        "Repository": "skywatcher-pr",
        "Record_ID": "obs_" + "a" * 32,
        "Source_X": -66.0,
        "Source_Y": 18.35,
        "Source_CRS": "EPSG:4326",
        "Coordinate_Evidence_State": "VERIFIED_SOURCE_COORDINATE",
        "Uncertainty_Class": "EXACT",
        "Spatial_Role": "POINT_LOCATION",
    }
    assert records[0]["Category"] == "test_observation"
    assert excluded == {"NO_EXACT_EVIDENCE": 1, "SYNTHETIC": 1}


def test_allow_synthetic_is_explicit():
    rows = [_row("obs_" + "d" * 32, synthetic=True)]
    sources, _, excluded = mod.project_observations(
        rows,
        repository="centinelas-pr",
        allow_synthetic=True,
    )
    assert len(sources) == 1
    assert excluded == {}


def test_invalid_coordinate_fails_closed():
    rows = [
        _row(
            "obs_" + "e" * 32,
            location={"lat": 91.0, "lon": -66.0},
        )
    ]
    with pytest.raises(mod.SourceExportError, match="out-of-range"):
        mod.project_observations(rows, repository="ovnis-pr")


def test_duplicate_observation_identity_fails_closed(tmp_path):
    path = tmp_path / "observations.jsonl"
    row = _row("obs_" + "f" * 32)
    path.write_text(json.dumps(row) + "\n" + json.dumps(row) + "\n")
    with pytest.raises(mod.SourceExportError, match="duplicate"):
        mod._read_jsonl(path)
