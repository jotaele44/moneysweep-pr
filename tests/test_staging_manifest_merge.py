"""build_staging_manifest merge semantics: a partial checkout never erases
holdings recorded by another environment (the pre-fix behavior wiped all 25
committed entries when run in this deny-all-gitignore clone)."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from scripts.build_staging_manifest import build_manifest
from scripts.gap_analysis_builder import _STAGING_MANIFEST_CACHE, _file_status

pytestmark = pytest.mark.unit


def _make_root(tmp_path: Path, committed: dict, local_csvs: dict[str, str]) -> Path:
    (tmp_path / "data" / "manifests").mkdir(parents=True)
    (tmp_path / "data" / "manifests" / "staging_masters.json").write_text(
        json.dumps({"schema_version": "staging_masters_v1", "files": committed}),
        encoding="utf-8",
    )
    processed = tmp_path / "data" / "staging" / "processed"
    processed.mkdir(parents=True)
    for name, body in local_csvs.items():
        with (processed / name).open("w", encoding="utf-8", newline="") as f:
            csv.writer(f, lineterminator="\n").writerows(
                [line.split(",") for line in body.splitlines()]
            )
    return tmp_path


COMMITTED = {
    "data/staging/processed/absent_master.csv": {
        "row_count": 5147,
        "sha256": "deadbeef",
        "size_bytes": 999,
    },
    "data/staging/processed/present_master.csv": {
        "row_count": 1,
        "sha256": "stale",
        "size_bytes": 1,
    },
}


def test_merge_preserves_absent_and_updates_present(tmp_path):
    root = _make_root(
        tmp_path, COMMITTED, {"present_master.csv": "a,b\n1,2\n3,4", "new_master.csv": "a\nx"}
    )
    files = build_manifest(root)["files"]
    # absent file's committed entry survives untouched
    assert files["data/staging/processed/absent_master.csv"]["row_count"] == 5147
    assert files["data/staging/processed/absent_master.csv"]["sha256"] == "deadbeef"
    # locally-present file is re-measured, not copied
    assert files["data/staging/processed/present_master.csv"]["row_count"] == 2
    assert files["data/staging/processed/present_master.csv"]["sha256"] != "stale"
    # new local file is added
    assert files["data/staging/processed/new_master.csv"]["row_count"] == 1
    assert list(files) == sorted(files)


def test_prune_drops_absent_entries(tmp_path):
    root = _make_root(tmp_path, COMMITTED, {"present_master.csv": "a,b\n1,2"})
    files = build_manifest(root, prune=True)["files"]
    assert "data/staging/processed/absent_master.csv" not in files
    assert files["data/staging/processed/present_master.csv"]["row_count"] == 1


def test_file_status_preserves_zero_row_manifest_states(tmp_path):
    root = _make_root(
        tmp_path,
        {
            "data/staging/processed/header_only.csv": {
                "row_count": 0,
                "sha256": "header",
                "size_bytes": 42,
                "status": "header_only",
            },
            "data/staging/processed/empty.csv": {
                "row_count": 0,
                "sha256": "empty",
                "size_bytes": 0,
                "status": "empty",
            },
            "data/staging/processed/legacy_zero.csv": {
                "row_count": 0,
                "sha256": "legacy",
                "size_bytes": 42,
            },
        },
        {},
    )
    _STAGING_MANIFEST_CACHE.pop(str(root), None)

    assert _file_status(root, "data/staging/processed/header_only.csv")["status"] == ("header_only")
    assert _file_status(root, "data/staging/processed/empty.csv")["status"] == "empty"
    assert _file_status(root, "data/staging/processed/legacy_zero.csv")["status"] == ("missing")
    assert _file_status(root, "data/staging/processed/absent.csv")["status"] == "missing"
