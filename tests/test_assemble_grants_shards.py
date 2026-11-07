from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from scripts.download_grants import MASTER_COLUMNS
from tools import assemble_grants_shards
from tools.operator_corpus_common import sha256_file


PLAN = [
    {
        "shard_id": "grants_pop-fy2024-fy2024",
        "pass_name": "grants_pop",
        "fy_start": 2024,
        "fy_end": 2024,
        "timeout_minutes": 360,
    },
    {
        "shard_id": "grants_pop-fy2025-fy2025",
        "pass_name": "grants_pop",
        "fy_start": 2025,
        "fy_end": 2025,
        "timeout_minutes": 360,
    },
]


def _write_shard(root: Path, shard: dict[str, object]) -> Path:
    relative = f"data/staging/raw/grants/{shard['pass_name']}_fy{shard['fy_start']}.csv"
    raw_path = root / relative
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    row = {column: "" for column in MASTER_COLUMNS}
    row["award_id"] = f"AWARD-{shard['fy_start']}"
    pd.DataFrame([row], columns=MASTER_COLUMNS).to_csv(raw_path, index=False)
    summary = {
        "schema_version": "moneysweep.grants_download/v2",
        "only_pass": shard["pass_name"],
        "fy_start": shard["fy_start"],
        "fy_end": shard["fy_end"],
        "master_built": False,
        "errors": [],
        "missing_raw_files": [],
        "expected_raw_files": [relative],
        "raw_files": [
            {
                "path": relative,
                "sha256": sha256_file(raw_path),
                "bytes": raw_path.stat().st_size,
                "rows": 1,
                "columns": MASTER_COLUMNS,
            }
        ],
    }
    summary_path = root / "certification_out/grants_shards" / f"{shard['shard_id']}.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary), encoding="utf-8")
    return summary_path


def test_assembly_requires_and_copies_the_exact_verified_set(monkeypatch, tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    output = tmp_path / "output"
    monkeypatch.setattr(assemble_grants_shards, "build_grants_shard_plan", lambda: PLAN)
    for shard in PLAN:
        _write_shard(artifacts, shard)

    report = assemble_grants_shards.assemble_grants_shards(
        artifacts_root=artifacts,
        output_dir=output,
    )

    assert report["complete"] is True
    assert report["expected_shards"] == report["observed_shards"] == 2
    assert report["expected_raw_files"] == report["verified_raw_files"] == 2
    assert report["copied_raw_files"] == 2
    assert sorted(path.name for path in output.glob("*.csv")) == [
        "grants_pop_fy2024.csv",
        "grants_pop_fy2025.csv",
    ]


def test_assembly_fails_closed_on_missing_summary(monkeypatch, tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    output = tmp_path / "output"
    monkeypatch.setattr(assemble_grants_shards, "build_grants_shard_plan", lambda: PLAN)
    _write_shard(artifacts, PLAN[0])

    report = assemble_grants_shards.assemble_grants_shards(
        artifacts_root=artifacts,
        output_dir=output,
    )

    assert report["complete"] is False
    assert "missing_shard_summary:grants_pop-fy2025-fy2025" in report["errors"]
    assert list(output.iterdir()) == []


def test_assembly_fails_closed_on_hash_or_schema_mismatch(monkeypatch, tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    output = tmp_path / "output"
    monkeypatch.setattr(assemble_grants_shards, "build_grants_shard_plan", lambda: PLAN)
    paths = [_write_shard(artifacts, shard) for shard in PLAN]
    summary = json.loads(paths[0].read_text(encoding="utf-8"))
    summary["raw_files"][0]["sha256"] = "0" * 64
    summary["raw_files"][0]["columns"] = ["wrong"]
    paths[0].write_text(json.dumps(summary), encoding="utf-8")

    report = assemble_grants_shards.assemble_grants_shards(
        artifacts_root=artifacts,
        output_dir=output,
    )

    assert report["complete"] is False
    assert any("raw_file_sha256_mismatch" in error for error in report["errors"])
    assert any("raw_file_schema_mismatch" in error for error in report["errors"])
    assert report["verified_raw_files"] == 1
    assert list(output.iterdir()) == []


def test_assembly_rejects_unexpected_summary_and_producer_error(
    monkeypatch, tmp_path: Path
) -> None:
    artifacts = tmp_path / "artifacts"
    output = tmp_path / "output"
    monkeypatch.setattr(assemble_grants_shards, "build_grants_shard_plan", lambda: PLAN)
    paths = [_write_shard(artifacts, shard) for shard in PLAN]
    summary = json.loads(paths[0].read_text(encoding="utf-8"))
    summary["errors"] = ["upstream blocked"]
    paths[0].write_text(json.dumps(summary), encoding="utf-8")
    extra = paths[0].with_name("unexpected.json")
    extra.write_text(paths[0].read_text(encoding="utf-8"), encoding="utf-8")

    report = assemble_grants_shards.assemble_grants_shards(
        artifacts_root=artifacts,
        output_dir=output,
    )

    assert report["complete"] is False
    assert "unexpected_shard_summary:unexpected" in report["errors"]
    assert any("producer_error:upstream blocked" in error for error in report["errors"])
    assert list(output.iterdir()) == []
