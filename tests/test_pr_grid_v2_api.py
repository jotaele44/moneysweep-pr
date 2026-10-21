"""Shared API regressions for domain-owned PR Grid V2 Cell_Profile serving."""

from __future__ import annotations

import hashlib
import json

import pytest
from fastapi import HTTPException

from server.backend.grid_v2_api import (
    PROFILE_ROOT_ENV,
    ROOT,
    cell_profile,
    router,
)


def _repo_slug() -> str:
    payload = json.loads((ROOT / "federation.json").read_text(encoding="utf-8"))
    return payload["repository_full_name"].rsplit("/", 1)[-1]


def _pin() -> dict:
    return json.loads(
        (ROOT / "federation/spatial/pr_grid_geographic_v2.pin.json").read_text(
            encoding="utf-8"
        )
    )


def test_api_router_is_mounted_by_repository_entrypoint():
    candidates = [
        ROOT / "server/backend/app.py",
        ROOT / "server/backend/main.py",
    ]
    assert any(
        path.exists()
        and "grid_v2_router" in path.read_text(encoding="utf-8")
        and "include_router(grid_v2_router)" in path.read_text(encoding="utf-8")
        for path in candidates
    )


def test_unconfigured_profile_response_always_has_grid_identity(monkeypatch):
    monkeypatch.delenv(PROFILE_ROOT_ENV, raising=False)
    routes = {route.path for route in router.routes}
    assert "/api/grid/v2/profile/{level}/{cell_id}" in routes
    assert "/api/grid/v2/identity/{level}" in routes
    payload = cell_profile("L1", "PRG2:L1:R075:C0234")
    assert payload["Data_State"] == "NO_DATA"
    assert payload["Grid_Identity"]["Grid_ID"] == "PR_GRID_GEOGRAPHIC_V2"
    assert payload["Grid_Identity"]["Grid_Version"] == "2.0.0-rc1"
    assert payload["Grid_Identity"]["Cell_ID"] == "PRG2:L1:R075:C0234"
    assert payload["Geometry_Included"] is False


def test_receipt_verified_profile_is_served(monkeypatch, tmp_path):
    consumer = _repo_slug()
    pin = _pin()
    level = pin["default_level"]
    cell = {
        "L0": "PRG2:L0:R010:C0010",
        "L1": "PRG2:L1:R020:C0020",
        "L2": "PRG2:L2:R040:C0040",
        "L3": "PRG2:L3:R080:C0080",
    }[level]

    from federation.spatial import pr_grid_v2_runtime as grid

    identity = grid.grid_identity(
        grid.load_pin(
            ROOT / "federation/spatial/pr_grid_geographic_v2.pin.json",
            expected_consumer=consumer,
            required_level=level,
        ),
        level=level,
        cell_id=cell,
    )
    row = {
        "Grid_Identity": identity,
        "Repository": consumer,
        "Cell_ID": cell,
        "Data_State": "ZERO_RECORDS",
        "Coverage_State": "VERIFIED",
        "Record_Count": 0,
        "Geometry_Included": False,
        "Grid_Deep_Link": (
            f"/grid/PR_GRID_GEOGRAPHIC_V2/2.0.0-rc1/{level}/{cell}"
        ),
    }

    directory = tmp_path / consumer
    directory.mkdir()
    artifact = directory / f"{level}.jsonl"
    artifact.write_text(
        json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    base_identity = dict(identity)
    base_identity.pop("Cell_ID")
    receipt = {
        "Output_SHA256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
        "Output_Bytes": artifact.stat().st_size,
        "Repository": consumer,
        "Grid_Identity": base_identity,
        "Geometry_Copied": False,
        "State": "CANDIDATE_NOT_CANONICAL",
    }
    (directory / f"{level}.receipt.json").write_text(
        json.dumps(receipt) + "\n",
        encoding="utf-8",
    )

    monkeypatch.setenv(PROFILE_ROOT_ENV, str(tmp_path))
    result = cell_profile(level, cell)
    assert result["Grid_Identity"] == identity
    assert result["Data_State"] == "ZERO_RECORDS"
    assert result["Profile_Storage_State"] == "CONFIGURED"


def test_wrong_grid_level_fails_closed():
    with pytest.raises(HTTPException) as exc:
        cell_profile("L4", "PRG2:L1:R075:C0234")
    assert exc.value.status_code == 503


def test_local_pin_must_match_repository_identity(tmp_path, monkeypatch):
    import server.backend.grid_v2_api as api

    payload = _pin()
    payload["consumer"] = "thehub-pr"
    payload["default_level"] = "L1"
    wrong = tmp_path / "wrong-pin.json"
    wrong.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(api, "PIN_PATH", wrong)
    with pytest.raises(HTTPException) as exc:
        api.cell_profile("L1", "PRG2:L1:R020:C0020")
    assert exc.value.status_code == 503
