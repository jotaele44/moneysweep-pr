from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

import tools.derive_certification_truth as truth
from tools.operator_corpus_common import (
    csv_rows,
    load_sources,
    sha256_file,
    source_definition_digest,
    source_ids_digest,
)

pytestmark = pytest.mark.unit


def _source(*, min_rows: int = 1, output: str = "data/staging/processed/a.csv") -> dict:
    return {
        "source_id": "alpha",
        "family": "test",
        "required": True,
        "authentication": "none",
        "producer_script": "scripts/alpha.py",
        "expected_outputs": [output],
        "validation_threshold": {"min_rows": min_rows},
        "update_cadence": "weekly",
    }


def _registry(root: Path, source: dict) -> None:
    path = root / "registries/source_registry.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(
        yaml.safe_dump(
            {
                "schema_version": "test_v1",
                "sources": [source],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def _csv(root: Path, rel: str, rows: list[str]) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("id\n" + "\n".join(rows) + ("\n" if rows else ""), encoding="utf-8")
    return path


def _receipt(root: Path, source: dict, output: Path) -> Path:
    sources, _ = load_sources(root)
    payload = {
        "schema_version": "moneysweep.operator_evidence/v1",
        "source_id": "alpha",
        "acquisition": {
            "producer": "scripts/alpha.py",
            "producer_sha": "a" * 40,
            "completed_at": "2026-08-31T12:00:00+00:00",
            "source_url": "https://example.invalid/alpha",
            "http_status": 200,
        },
        "registry": {
            "source_ids_sha256": source_ids_digest(sources),
            "source_definition_sha256": source_definition_digest(source),
        },
        "outputs": [
            {
                "path": output.relative_to(root).as_posix(),
                "sha256": sha256_file(output),
                "bytes": output.stat().st_size,
                "rows": csv_rows(output),
                "content_type": "text/csv",
            }
        ],
        "validation": {
            "schema_valid": True,
            "positive_rows": True,
            "coverage_contract_pass": False,
        },
    }
    path = root / "receipts/alpha.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_header_only_csv_is_not_materialized(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    source = _source(min_rows=1)
    _registry(root, source)
    _csv(root, source["expected_outputs"][0], [])

    result = truth.evaluate_output(
        evidence_root=root,
        source=source,
        output_path=source["expected_outputs"][0],
    )

    assert result["exists"] is True
    assert result["rows"] == 0
    assert result["usable"] is False
    assert result["reason"] == "below_min_rows:0<1"


def test_min_rows_is_enforced(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    source = _source(min_rows=3)
    _registry(root, source)
    _csv(root, source["expected_outputs"][0], ["1", "2"])

    result = truth.evaluate_output(
        evidence_root=root,
        source=source,
        output_path=source["expected_outputs"][0],
    )

    assert result["rows"] == 2
    assert result["usable"] is False
    assert result["reason"] == "below_min_rows:2<3"


def test_invalid_json_is_not_usable(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    source = _source(output="data/manifests/alpha.json")
    _registry(root, source)
    output = root / source["expected_outputs"][0]
    output.parent.mkdir(parents=True)
    output.write_text("{not-json", encoding="utf-8")

    result = truth.evaluate_output(
        evidence_root=root,
        source=source,
        output_path=source["expected_outputs"][0],
    )

    assert result["exists"] is True
    assert result["usable"] is False
    assert result["reason"] == "json_empty_or_invalid"


def test_truth_scope_is_deterministic_and_does_not_invent_coverage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "repo"
    source = _source(min_rows=1)
    _registry(root, source)
    output = _csv(root, source["expected_outputs"][0], ["1", "2"])
    _receipt(root, source, output)
    monkeypatch.setattr(truth, "_classify", lambda source, root: "api_producer")
    as_of = datetime(2026, 8, 31, 12, 30, tzinfo=timezone.utc)

    first = truth.derive(
        root=root,
        evidence_root=root,
        receipts_dir=root / "receipts",
        scope_dir=root / "scope-a",
        as_of=as_of,
        operator_corpus_id="b" * 64,
    )
    second = truth.derive(
        root=root,
        evidence_root=root,
        receipts_dir=root / "receipts",
        scope_dir=root / "scope-b",
        as_of=as_of,
        operator_corpus_id="b" * 64,
    )

    assert first["scope_manifest"]["scope_id"] == second["scope_manifest"]["scope_id"]
    source_truth = first["truth"]["sources"][0]
    assert source_truth["materialization_status"] == "fully_materialized"
    assert source_truth["coverage_status"] == "unverifiable"
    assert "receipt_coverage_not_proven" in source_truth["coverage_blockers"]
    assert first["truth"]["summary"]["required_fully_materialized"] == 1
    assert first["truth"]["summary"]["automatable_total"] == 1
