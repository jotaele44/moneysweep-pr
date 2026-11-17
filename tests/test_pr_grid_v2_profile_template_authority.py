"""Exact authority lock for the shared PR grid V2 Cell_Profile templates."""

from __future__ import annotations

import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# The thehub-pr commit whose federation-templates/spatial/ bytes these files are
# rendered from (Cell_Profile pr-grid-v2-cell-profile/1.2). It is the template
# authority, not the grid authority: the grid stays pinned by
# federation/spatial/pr_grid_geographic_v2.pin.json.
THEHUB_PROFILE_TEMPLATE_COMMIT = "a68ffed1111285c87f5c0d450858c58fa5884642"
PROFILE_GIT_BLOB_SHA1 = "e245d91a9b5da829d1bbdaec329958c08e057701"
MATERIALIZER_GIT_BLOB_SHA1 = "33557e2e60b3d0f79545ac5269f82abc0a6b3391"
PROFILE_TEST_GIT_BLOB_SHA1 = "c2c3e34e0396d8b260fa13df3f6f0902becaa857"


def _git_blob_sha1(path: Path) -> str:
    payload = path.read_bytes()
    header = f"blob {len(payload)}\0".encode("ascii")
    return hashlib.sha1(header + payload).hexdigest()


def test_grid_v2_profile_templates_match_thehub_authority():
    assert len(THEHUB_PROFILE_TEMPLATE_COMMIT) == 40
    assert (
        _git_blob_sha1(ROOT / "federation/spatial/pr_grid_v2_profiles.py") == PROFILE_GIT_BLOB_SHA1
    )
    assert (
        _git_blob_sha1(ROOT / "federation/spatial/materialize_pr_grid_v2_profiles.py")
        == MATERIALIZER_GIT_BLOB_SHA1
    )
    assert _git_blob_sha1(ROOT / "tests/test_pr_grid_v2_profiles.py") == PROFILE_TEST_GIT_BLOB_SHA1
