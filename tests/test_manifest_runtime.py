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


@pytest.mark.unit
def test_duplicate_rate_is_bounded_zero_to_one(tmp_path):
    """duplicate_rate must always be in [0, 1]; old formula could exceed 1."""
    target = tmp_path / "data" / "staging" / "processed" / "dup_test.csv"
    target.parent.mkdir(parents=True)
    # 10 rows, award_id repeats 9 times → 9 duplicate rows, 1 unique key
    # Old formula: 9 / 1 = 9.0  ← invalid
    # New formula: 9 / (9 + 1) = 0.9 ← valid
    rows = ["award_id,amount\n"] + ["A001,100\n"] * 10
    target.write_text("".join(rows), encoding="utf-8")
    item = mr.profile_file(target, root=tmp_path)
    dr = item["duplicate_rate"]
    assert 0.0 <= dr <= 1.0, f"duplicate_rate {dr} is out of [0, 1]"
    assert abs(dr - 0.9) < 1e-9


@pytest.mark.unit
def test_duplicate_rate_zero_when_all_unique(tmp_path):
    target = tmp_path / "data" / "staging" / "processed" / "unique_test.csv"
    target.parent.mkdir(parents=True)
    rows = ["award_id,amount\n"] + [f"A{i:03d},100\n" for i in range(5)]
    target.write_text("".join(rows), encoding="utf-8")
    item = mr.profile_file(target, root=tmp_path)
    assert item["duplicate_rate"] == 0.0


@pytest.mark.unit
def test_pw_number_preferred_over_award_id_as_pk(tmp_path):
    """FEMA PA rows share award_id but have unique pw_number; pw_number wins."""
    target = tmp_path / "data" / "staging" / "processed" / "fema_test.csv"
    target.parent.mkdir(parents=True)
    # 3 rows: same award_id (shared disaster), unique pw_number
    target.write_text(
        "pw_number,award_id,amount\nPW001,DISASTER1,100\nPW002,DISASTER1,200\nPW003,DISASTER1,300\n",
        encoding="utf-8",
    )
    item = mr.profile_file(target, root=tmp_path)
    assert item.get("pk_field") == "pw_number"
    assert item["duplicate_rate"] == 0.0


@pytest.mark.unit
def test_profile_records_columns_for_drift_detection(tmp_path):
    """profile_file must record the column list in order so downstream
    schema-drift comparisons can diff two manifests."""
    target = tmp_path / "data" / "staging" / "processed" / "drift_a.csv"
    target.parent.mkdir(parents=True)
    target.write_text("alpha,beta,gamma\n1,2,3\n", encoding="utf-8")
    item = mr.profile_file(target, root=tmp_path)
    assert item["columns"] == ["alpha", "beta", "gamma"]
    assert item["column_count"] == 3


@pytest.mark.unit
def test_sha256_changes_when_file_content_changes(tmp_path):
    """profile_file must re-hash on every call; no stale cache."""
    target = tmp_path / "data" / "staging" / "processed" / "hash_test.csv"
    target.parent.mkdir(parents=True)
    target.write_text("a,b\n1,2\n", encoding="utf-8")
    first = mr.profile_file(target, root=tmp_path)["sha256"]
    # Append a row; hash must shift.
    with target.open("a", encoding="utf-8") as f:
        f.write("3,4\n")
    second = mr.profile_file(target, root=tmp_path)["sha256"]
    assert first != second
    assert len(first) == 64 and len(second) == 64


@pytest.mark.integration
def test_per_source_manifest_includes_columns_field(tmp_path):
    """write_per_source_manifest persists the columns list inside each
    file profile, so drift detection works against the written JSON."""
    # write_per_source_manifest calls source_by_id which loads the
    # registry; copy the production registry into tmp_path so the
    # lookup succeeds in isolation.
    repo_root = Path(__file__).resolve().parents[1]
    src_reg_dir = repo_root / "registries"
    dst_reg_dir = tmp_path / "registries"
    dst_reg_dir.mkdir(parents=True)
    for f in src_reg_dir.glob("source_registry.*"):
        shutil.copy(f, dst_reg_dir / f.name)

    target = tmp_path / "data" / "staging" / "processed" / "src.csv"
    target.parent.mkdir(parents=True)
    target.write_text("one,two\n1,2\n3,4\n", encoding="utf-8")
    profile = mr.profile_file(target, root=tmp_path)
    # Use a source_id that is unlikely to exist; the function falls back
    # to {"source_id": source_id} so this still exercises the write path.
    manifest_path = mr.write_per_source_manifest(
        tmp_path,
        source_id="synthetic_test_source",
        files=[profile],
    )
    payload = json.loads(manifest_path.read_text())
    assert payload["file_count"] == 1
    assert payload["files"][0]["columns"] == ["one", "two"]
