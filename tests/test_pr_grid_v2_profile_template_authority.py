"""Exact authority lock for the shared PR grid V2 Cell_Profile templates."""

from __future__ import annotations

import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
THEHUB_AUTHORITY_COMMIT = "0663bfa77740dceff3eb70855f2164112ce47c44"
PROFILE_GIT_BLOB_SHA1 = "c4e174b4626083ef3e1866274e87e8aaea9f81a2"
PROFILE_TEST_GIT_BLOB_SHA1 = "3f74d64046ef19b4b8f4718b3a50d5eed902877c"


def _git_blob_sha1(path: Path) -> str:
    payload = path.read_bytes()
    header = f"blob {len(payload)}\0".encode("ascii")
    return hashlib.sha1(header + payload).hexdigest()


def test_grid_v2_profile_template_matches_thehub_authority():
    assert len(THEHUB_AUTHORITY_COMMIT) == 40
    assert _git_blob_sha1(
        ROOT / "federation/spatial/pr_grid_v2_profiles.py"
    ) == PROFILE_GIT_BLOB_SHA1
    assert _git_blob_sha1(
        ROOT / "tests/test_pr_grid_v2_profiles.py"
    ) == PROFILE_TEST_GIT_BLOB_SHA1
