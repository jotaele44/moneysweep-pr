"""Fail-closed pin for Spiderweb PR_GRID_GEOGRAPHIC_V2 RC1."""

import json
from pathlib import Path

PIN = json.loads(
    (
        Path(__file__).resolve().parents[1]
        / "federation/spatial/pr_grid_geographic_v2.pin.json"
    ).read_text()
)


def test_pr_grid_v2_pin_is_exact():
    assert PIN["consumer"] == "moneysweep-pr"
    assert PIN["geometry_authority"] == "spiderweb-pr"
    assert PIN["authority_commit"] == "0c66e13d14232c0d7cbcbc179b3655904777dc71"
    assert PIN["grid_id"] == "PR_GRID_GEOGRAPHIC_V2"
    assert PIN["grid_version"] == "2.0.0-rc1"
    assert PIN["crs"] == "EPSG:6566"
    assert PIN["grid_manifest_sha256"] == "8902af188ad449955119016f5747fe2393c582d9ed552fb03bcaecd9ab510aa4"
    assert PIN["cell_schema_sha256"] == "1c173aee4b21b9baa545b656735155f2236a87c436d467a12132ef53b2592f5d"
    assert PIN["binding_schema_sha256"] == "dabc461e47134b3b150be9aeb23b3d0097563493b33b3187538255e06b16a022"
    assert PIN["mask_schema_sha256"] == "0b31b717d274b19686bf7f47edbabdaec31c86800f2ca7f1e73ffb663600978b"
    assert PIN["default_level"] == "L1"
    assert PIN["allowed_levels"] == ["L0", "L1", "L2", "L3"]
    assert PIN["geometry_mode"] == "REFERENCE_ONLY"
    assert PIN["local_geometry_copy"] is False
    assert PIN["v1_coexistence"] == "PRESERVE_UNCHANGED"
    assert PIN["compatibility_policy"] == "FAIL_CLOSED"


def test_provider_blockers_do_not_promote_source_certification():
    blockers = {
        row["id"]: row["affects_grid_identity"]
        for row in PIN["external_provider_blockers"]
    }
    assert blockers == {"QA-D24-001": False, "QA-D24-003": False}
