"""Tests for the manifest runtime."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from contract_sweeper.runtime import manifest_runtime as mr

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "r5"


@pytest.mark.unit
def test_profile_csv_file_records_row_and_column_counts(tmp_path):
    src = FIXTURES / "sample_contracts.csv"
    dst = tmp_path / "data" / "staging" / "processed"
    dst.mkdir(parents=True)
    target = dst / "sample_contracts.csv"
    shutil.copy(src, target)
    item = mr.profile_file(target, root=tmp_path)
    assert item["row_count"] == 5
    assert item["column_count"] > 0
    assert item["validation_status"] == "present"
    assert item["sha256"] and len(item["sha256"]) == 64
    assert item["entity_match_rate_pct"] is not None
    assert item["duplicate_rate"] == 0.0


@pytest.mark.unit
def test_profile_includes_year_coverage_pct(tmp_path):
    src = FIXTURES / "sample_contracts.csv"
    dst = tmp_path / "data" / "staging" / "processed"
    dst.mkdir(parents=True)
    target = dst / "sample_contracts.csv"
    shutil.copy(src, target)
    item = mr.profile_file(
        target,
        root=tmp_path,
        expected_years=[2022, 2023, 2024, 2025],
    )
    assert item["year_coverage_pct"] is not None
    assert item["year_coverage_pct"] >= 0.5


@pytest.mark.unit
def test_write_canonical_manifest_emits_json_and_csv(tmp_path):
    src = FIXTURES / "sample_contracts.csv"
    dst = tmp_path / "data" / "staging" / "processed"
    dst.mkdir(parents=True)
    target = dst / "sample_contracts.csv"
    shutil.copy(src, target)
    files = mr.scan_repo(tmp_path)
    paths = mr.write_canonical_manifest(tmp_path, files)
    assert paths["json"].exists()
    assert paths["csv"].exists()
    payload = json.loads(paths["json"].read_text())
    assert payload["manifest_type"] == "canonical_source_manifest"
    assert payload["file_count"] >= 1


@pytest.mark.unit
def test_empty_csv_marked_empty_or_header_only(tmp_path):
    target = tmp_path / "data" / "staging" / "processed" / "empty.csv"
    target.parent.mkdir(parents=True)
    target.write_text("col_a,col_b\n", encoding="utf-8")
    item = mr.profile_file(target, root=tmp_path)
    assert item["empty_or_header_only"] is True
    assert item["validation_status"] == "empty_or_header_only"
