"""Tests for scripts/gap_analysis_builder.py."""
import csv
import json

import pytest

from scripts.gap_analysis_builder import build_gap_analysis, _file_status


@pytest.fixture
def gap_repo(tmp_path):
    reg_dir = tmp_path / "registries"
    reg_dir.mkdir(parents=True)
    reg = {
        "sources": [
            {
                "source_id": "source_a",
                "family": "federal",
                "required": True,
                "authentication": "none",
                "expected_outputs": ["data/staging/processed/source_a.csv"],
                "validation_threshold": {"min_rows": 1},
            },
            {
                "source_id": "source_b",
                "family": "federal",
                "required": True,
                "authentication": "none",
                "expected_outputs": ["data/staging/processed/source_b.csv"],
                "validation_threshold": {"min_rows": 1},
            },
            {
                "source_id": "source_c",
                "family": "territorial",
                "required": False,
                "authentication": "none",
                "expected_outputs": ["data/staging/processed/source_c.csv"],
                "validation_threshold": {"min_rows": 1},
            },
        ]
    }
    (reg_dir / "source_registry.json").write_text(json.dumps(reg), encoding="utf-8")

    proc = tmp_path / "data" / "staging" / "processed"
    proc.mkdir(parents=True)
    # source_a present with data
    with (proc / "source_a.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["id", "name"])
        w.writeheader()
        w.writerow({"id": "1", "name": "Test"})
    # source_b missing
    # source_c empty
    (proc / "source_c.csv").write_text("", encoding="utf-8")

    return tmp_path


@pytest.mark.unit
def test_build_gap_returns_summary_keys(gap_repo):
    result = build_gap_analysis(gap_repo)
    for key in ("total_sources", "required_sources", "fully_materialized",
                "not_materialized", "coverage_rate", "required_coverage_rate"):
        assert key in result


@pytest.mark.unit
def test_build_gap_counts(gap_repo):
    result = build_gap_analysis(gap_repo)
    assert result["total_sources"] == 3
    assert result["required_sources"] == 2
    assert result["fully_materialized"] == 1   # source_a
    assert result["not_materialized"] == 1     # source_b (required, missing)
    assert result["partially_materialized"] == 1  # source_c (optional, empty file)


@pytest.mark.unit
def test_build_gap_required_coverage_rate(gap_repo):
    result = build_gap_analysis(gap_repo)
    # 1 of 2 required sources materialized → 0.5
    assert abs(result["required_coverage_rate"] - 0.5) < 0.01


@pytest.mark.unit
def test_build_gap_emits_csv(gap_repo):
    build_gap_analysis(gap_repo)
    csv_path = gap_repo / "reports" / "gap_analysis_report.csv"
    assert csv_path.exists()
    with csv_path.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 3
    statuses = {r["source_id"]: r["source_status"] for r in rows}
    assert statuses["source_a"] == "fully_materialized"
    assert statuses["source_b"] == "not_materialized"


@pytest.mark.unit
def test_build_gap_emits_json(gap_repo):
    build_gap_analysis(gap_repo)
    json_path = gap_repo / "reports" / "gap_analysis_report.json"
    assert json_path.exists()
    payload = json.loads(json_path.read_text())
    assert payload["schema_version"] == "r5_v1"


@pytest.mark.unit
def test_build_gap_required_sources_sorted_first(gap_repo):
    build_gap_analysis(gap_repo)
    csv_path = gap_repo / "reports" / "gap_analysis_report.csv"
    with csv_path.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    required_rows = [r for r in rows if r["required"] == "True"]
    optional_rows = [r for r in rows if r["required"] == "False"]
    # All required rows should appear before optional in the sorted output
    if required_rows and optional_rows:
        last_req_idx = max(rows.index(r) for r in required_rows)
        first_opt_idx = min(rows.index(r) for r in optional_rows)
        assert last_req_idx < first_opt_idx


@pytest.mark.unit
def test_file_status_missing(tmp_path):
    status = _file_status(tmp_path, "nonexistent/file.csv")
    assert status["status"] == "missing"
    assert status["row_count"] == 0


@pytest.mark.unit
def test_file_status_empty(tmp_path):
    p = tmp_path / "empty.csv"
    p.write_text("", encoding="utf-8")
    status = _file_status(tmp_path, "empty.csv")
    assert status["status"] == "empty"


@pytest.mark.unit
def test_file_status_present(tmp_path):
    p = tmp_path / "data.csv"
    with p.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["a"])
        w.writeheader()
        w.writerow({"a": "1"})
    status = _file_status(tmp_path, "data.csv")
    assert status["status"] == "present"
    assert status["row_count"] == 1
