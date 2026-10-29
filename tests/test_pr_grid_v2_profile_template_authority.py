"""Exact authority lock for shared PR grid V2 Cell_Profile templates."""

from __future__ import annotations

import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
THEHUB_PROFILE_TEMPLATE_COMMIT = "d7716d00c0ab40a79cee06e192508924ef17d9eb"
PROFILE_GIT_BLOB_SHA1 = "704ac0dc222b5a980811b84312961f66cc3ee309"
MATERIALIZER_GIT_BLOB_SHA1 = "66a3c995118353bce0260c874901496b8847acc6"
PROFILE_TEST_GIT_BLOB_SHA1 = "6eb7c9d4699691b1f1e25f65351441b51a8382fb"


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
