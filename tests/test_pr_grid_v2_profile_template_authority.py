"""Exact authority lock for shared PR grid V2 runtime/profile templates."""

from __future__ import annotations

import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
THEHUB_AUTHORITY_COMMIT = "9adf06d31ddffef1010d3d6461373ca3300f48be"
RUNTIME_GIT_BLOB_SHA1 = "a25e375a391499f0dc88c7d7344528d82e5c74ab"
PROFILE_GIT_BLOB_SHA1 = "0e9cd5a421e87d707d99d13a25e713a324614fa2"
MATERIALIZER_GIT_BLOB_SHA1 = "33557e2e60b3d0f79545ac5269f82abc0a6b3391"
PROFILE_TEST_GIT_BLOB_SHA1 = "c2c3e34e0396d8b260fa13df3f6f0902becaa857"
SOURCE_EXPORT_GIT_BLOB_SHA1 = "c4a67c82e7a3507543662fd6a6e6b357bf163649"
SOURCE_EXPORT_TEST_GIT_BLOB_SHA1 = "bfaa6755abafd8b73ed216b72ea8e8330a8a1891"


def _git_blob_sha1(path: Path) -> str:
    payload = path.read_bytes()
    header = f"blob {len(payload)}\0".encode("ascii")
    return hashlib.sha1(header + payload).hexdigest()


def test_grid_v2_templates_match_thehub_authority():
    assert len(THEHUB_AUTHORITY_COMMIT) == 40
    expected = {
        ROOT / "federation/spatial/pr_grid_v2_runtime.py": RUNTIME_GIT_BLOB_SHA1,
        ROOT / "federation/spatial/pr_grid_v2_profiles.py": PROFILE_GIT_BLOB_SHA1,
        ROOT / "federation/spatial/materialize_pr_grid_v2_profiles.py": MATERIALIZER_GIT_BLOB_SHA1,
        ROOT / "tests/test_pr_grid_v2_profiles.py": PROFILE_TEST_GIT_BLOB_SHA1,
        ROOT / "federation/spatial/export_pr_grid_v2_exact_observations.py": SOURCE_EXPORT_GIT_BLOB_SHA1,
        ROOT / "tests/test_pr_grid_v2_source_export.py": SOURCE_EXPORT_TEST_GIT_BLOB_SHA1,
    }
    for path, expected_sha1 in expected.items():
        assert path.is_file(), path
        assert _git_blob_sha1(path) == expected_sha1, path
