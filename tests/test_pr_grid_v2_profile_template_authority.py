"""Exact authority lock for the shared PR grid V2 Cell_Profile templates."""

from __future__ import annotations

import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
THEHUB_AUTHORITY_COMMIT = "d916664504404b9deb68a9d3f6c811f86e564938"
PROFILE_GIT_BLOB_SHA1 = "e245d91a9b5da829d1bbdaec329958c08e057701"
PROFILE_TEST_GIT_BLOB_SHA1 = "c2c3e34e0396d8b260fa13df3f6f0902becaa857"


def _git_blob_sha1(path: Path) -> str:
    payload = path.read_bytes()
    header = f"blob {len(payload)}\0".encode("ascii")
    return hashlib.sha1(header + payload).hexdigest()


def test_grid_v2_profile_template_matches_thehub_authority():
    assert len(THEHUB_AUTHORITY_COMMIT) == 40
    assert (
        _git_blob_sha1(ROOT / "federation/spatial/pr_grid_v2_profiles.py") == PROFILE_GIT_BLOB_SHA1
    )
    assert _git_blob_sha1(ROOT / "tests/test_pr_grid_v2_profiles.py") == PROFILE_TEST_GIT_BLOB_SHA1
