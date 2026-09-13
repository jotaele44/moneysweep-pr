from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
import yaml

from tools.assemble_operator_workspace import assemble
from tools.operator_corpus_common import source_definition_digest, source_ids_digest

pytestmark = pytest.mark.unit


def _root(tmp_path: Path) -> tuple[Path, dict]:
    root = tmp_path / "repo"
    source = {
        "source_id": "alpha",
        "family": "test",
        "required": True,
        "authentication": "none",
        "producer_script": "scripts/alpha.py",
        "endpoint_url": "https://example.invalid/alpha",
        "expected_outputs": ["data/staging/processed/alpha.csv"],
        "validation_threshold": {"min_rows": 1},
        "update_cadence": "daily",
    }
    registry = root / "registries/source_registry.yaml"
    registry.parent.mkdir(parents=True)
    registry.write_text(
        yaml.safe_dump({"schema_version": "test_v1", "sources": [source]}, sort_keys=False),
        encoding="utf-8",
    )
    return root, source


def _bundle(root: Path, artifacts: Path, source: dict, lane: str, value: str = "a") -> Path:
    output_rel = "data/staging/processed/alpha.csv"
    output = artifacts / lane / output_rel
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(f"id,value\n1,{value}\n", encoding="utf-8")
    source_digest = source_ids_digest([source])
    receipt = {
        "schema_version": "moneysweep.operator_evidence/v1",
        "source_id": "alpha",
        "acquisition": {
            "producer": "scripts/alpha.py",
            "producer_sha": "a" * 40,
            "completed_at": "2026-09-13T12:00:00+00:00",
            "source_url": "https://example.invalid/alpha",
            "http_status": 200,
        },
        "registry": {
            "source_ids_sha256": source_digest,
            "source_definition_sha256": source_definition_digest(source),
        },
        "outputs": [
            {
                "path": output_rel,
                "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
                "bytes": output.stat().st_size,
                "rows": 1,
                "content_type": "text/csv",
            }
        ],
        "validation": {
            "schema_valid": True,
            "positive_rows": True,
            "coverage_contract_pass": False,
        },
    }
    receipt_path = artifacts / lane / "operator_evidence" / "alpha.json"
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(json.dumps(receipt, sort_keys=True), encoding="utf-8")
    return receipt_path


def test_identical_receipts_from_multiple_lanes_dedupe_safely(tmp_path: Path) -> None:
    root, source = _root(tmp_path)
    artifacts = tmp_path / "artifacts"
    _bundle(root, artifacts, source, "public")
    _bundle(root, artifacts, source, "keyless")

    workspace = tmp_path / "workspace"
    report = assemble(root=root, artifacts_root=artifacts, workspace_root=workspace)

    assert report["blockers"] == []
    assert report["assembled_source_count"] == 1
    assert report["discovered_receipt_files"] == 2
    assert report["authority_asserted"] is False
    assert (workspace / "data/staging/processed/alpha.csv").is_file()
    assert (workspace / "receipts/alpha.json").is_file()


def test_conflicting_receipts_for_same_source_fail_closed(tmp_path: Path) -> None:
    root, source = _root(tmp_path)
    artifacts = tmp_path / "artifacts"
    _bundle(root, artifacts, source, "public", value="a")
    _bundle(root, artifacts, source, "keyless", value="different")

    report = assemble(
        root=root,
        artifacts_root=artifacts,
        workspace_root=tmp_path / "workspace",
    )

    assert "alpha:conflicting_receipts" in report["blockers"]
    assert report["assembled_source_count"] == 0


def test_receipt_with_wrong_registry_digest_is_rejected(tmp_path: Path) -> None:
    root, source = _root(tmp_path)
    artifacts = tmp_path / "artifacts"
    receipt_path = _bundle(root, artifacts, source, "public")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["registry"]["source_ids_sha256"] = "0" * 64
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

    report = assemble(
        root=root,
        artifacts_root=artifacts,
        workspace_root=tmp_path / "workspace",
    )

    assert report["assembled_source_count"] == 0
    assert report["rejected_receipts"][0]["errors"] == ["registry_digest_mismatch"]
    assert "alpha:invalid_receipt" in report["blockers"]
