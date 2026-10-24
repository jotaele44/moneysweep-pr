from pathlib import Path

import yaml

from tools.audit_materialization_coverage import build


def _root(tmp_path: Path, source: dict) -> Path:
    root = tmp_path
    (root / "registries").mkdir()
    (root / "registries" / "source_registry.yaml").write_text(
        yaml.safe_dump({"schema_version": "test-v1", "sources": [source]}),
        encoding="utf-8",
    )
    return root


def _source(*outputs: str, min_rows: int = 1) -> dict:
    return {
        "source_id": "fixture",
        "family": "test",
        "required": True,
        "expected_outputs": list(outputs),
        "validation_threshold": {"min_rows": min_rows},
    }


def _fixture_row(report: dict) -> dict:
    return next(row for row in report["sources"] if row["source_id"] == "fixture")


def test_zero_row_csv_is_present_but_not_materialized(tmp_path: Path) -> None:
    rel = "data/staging/processed/fixture.csv"
    root = _root(tmp_path, _source(rel))
    path = root / rel
    path.parent.mkdir(parents=True)
    path.write_text("id,value\n", encoding="utf-8")

    report = build(root)
    row = _fixture_row(report)

    assert row["present_count"] == 1
    assert row["usable_count"] == 0
    assert row["local_status"] == "not_materialized"
    assert row["outputs"][0]["reason"] == "below_min_rows:0<1"
    assert report["local_truth_summary"]["required_fully_materialized"] == 0


def test_unreadable_csv_is_not_materialized(tmp_path: Path) -> None:
    rel = "data/staging/processed/fixture.csv"
    root = _root(tmp_path, _source(rel))
    path = root / rel
    path.parent.mkdir(parents=True)
    path.write_bytes(b"\xff\xfe\x00\x80")

    row = _fixture_row(build(root))

    assert row["present_count"] == 1
    assert row["usable_count"] == 0
    assert row["unreadable_csv_count"] == 1
    assert row["local_status"] == "not_materialized"
    assert row["outputs"][0]["reason"] == "csv_unreadable"


def test_positive_row_csv_is_fully_materialized(tmp_path: Path) -> None:
    rel = "data/staging/processed/fixture.csv"
    root = _root(tmp_path, _source(rel))
    path = root / rel
    path.parent.mkdir(parents=True)
    path.write_text("id,value\n1,ok\n", encoding="utf-8")

    report = build(root)
    row = _fixture_row(report)

    assert row["present_count"] == 1
    assert row["usable_count"] == 1
    assert row["local_status"] == "fully_materialized"
    assert row["outputs"][0]["data_rows"] == 1
    assert row["outputs"][0]["reason"] is None
    assert report["local_truth_summary"]["required_fully_materialized"] == 1


def test_min_rows_contract_is_enforced(tmp_path: Path) -> None:
    rel = "data/staging/processed/fixture.csv"
    root = _root(tmp_path, _source(rel, min_rows=2))
    path = root / rel
    path.parent.mkdir(parents=True)
    path.write_text("id,value\n1,ok\n", encoding="utf-8")

    row = _fixture_row(build(root))

    assert row["usable_count"] == 0
    assert row["local_status"] == "not_materialized"
    assert row["outputs"][0]["reason"] == "below_min_rows:1<2"


def test_empty_non_csv_and_empty_directory_do_not_materialize(tmp_path: Path) -> None:
    file_rel = "data/raw/fixture.bin"
    dir_rel = "data/raw/fixture_dir/"
    root = _root(tmp_path, _source(file_rel, dir_rel))
    file_path = root / file_rel
    file_path.parent.mkdir(parents=True)
    file_path.write_bytes(b"")
    (root / dir_rel).mkdir(parents=True)

    row = _fixture_row(build(root))

    assert row["present_count"] == 2
    assert row["usable_count"] == 0
    assert row["local_status"] == "not_materialized"
    reasons = {item["reason"] for item in row["outputs"]}
    assert reasons == {"empty_file", "directory_empty_or_missing"}


def test_partial_materialization_counts_only_usable_outputs(tmp_path: Path) -> None:
    good_rel = "data/staging/processed/good.csv"
    empty_rel = "data/staging/processed/empty.csv"
    root = _root(tmp_path, _source(good_rel, empty_rel))
    good = root / good_rel
    good.parent.mkdir(parents=True)
    good.write_text("id\n1\n", encoding="utf-8")
    (root / empty_rel).write_text("id\n", encoding="utf-8")

    row = _fixture_row(build(root))

    assert row["present_count"] == 2
    assert row["usable_count"] == 1
    assert row["local_status"] == "partially_materialized"
