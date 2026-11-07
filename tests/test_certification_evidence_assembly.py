from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from tools.assemble_certification_evidence import assemble
from tools.build_operator_corpus import build as build_operator_corpus
from tools.operator_corpus_common import (
    csv_rows,
    load_sources,
    sha256_file,
    source_definition_digest,
    source_ids_digest,
)
from tools.verify_operator_corpus import verify as verify_operator_corpus

pytestmark = pytest.mark.unit


def _source() -> dict:
    return {
        "source_id": "alpha",
        "family": "test",
        "required": True,
        "authentication": "none",
        "producer_script": "scripts/alpha.py",
        "expected_outputs": ["data/staging/processed/alpha.csv"],
        "schema_version": "test_v1",
        "validation_threshold": {"min_rows": 1},
        "update_cadence": "daily",
    }


def _write_registry(root: Path) -> dict:
    source = _source()
    path = root / "registries" / "source_registry.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(
        yaml.safe_dump(
            {
                "schema_version": "test_source_registry_v1",
                "sources": [source],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return source


def _write_artifact(
    *,
    registry_root: Path,
    artifacts_root: Path,
    artifact_name: str = "keyless-alpha",
    value: str = "ok",
) -> None:
    source = _source()
    sources, _ = load_sources(registry_root)
    artifact = artifacts_root / artifact_name
    output = artifact / "files" / "data/staging/processed/alpha.csv"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(f"id,value\n1,{value}\n", encoding="utf-8")

    receipt = {
        "schema_version": "moneysweep.operator_evidence/v1",
        "source_id": "alpha",
        "acquisition": {
            "producer": "scripts/alpha.py",
            "producer_sha": "a" * 40,
            "completed_at": "2026-09-25T12:00:00+00:00",
            "source_url": "https://example.invalid/alpha",
            "http_status": 200,
        },
        "registry": {
            "source_ids_sha256": source_ids_digest(sources),
            "source_definition_sha256": source_definition_digest(source),
        },
        "outputs": [
            {
                "path": "data/staging/processed/alpha.csv",
                "sha256": sha256_file(output),
                "bytes": output.stat().st_size,
                "rows": csv_rows(output),
                "content_type": "text/csv",
            }
        ],
        "validation": {
            "schema_valid": True,
            "positive_rows": True,
            "coverage_contract_pass": True,
        },
    }
    evidence = artifact / "operator_evidence"
    evidence.mkdir(parents=True)
    (evidence / "alpha.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    execution = {
        "schema_version": "moneysweep.keyless_execution/v2",
        "source_id": "alpha",
        "workflow_step_outcome": "success",
        "missing_expected_outputs": [],
        "standardized_receipt_emitted": True,
        "standardized_receipt_error": None,
        "runner_summary": {
            "ran": [
                {
                    "source": "alpha",
                    "status": "OK",
                    "rows": 1,
                    "error": "",
                }
            ]
        },
    }
    (artifact / "execution_receipt.json").write_text(
        json.dumps(execution, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def test_assembled_workspace_can_build_and_verify_corpus(tmp_path: Path) -> None:
    registry_root = tmp_path / "registry"
    artifacts_root = tmp_path / "artifacts"
    workspace = tmp_path / "workspace"
    receipts = tmp_path / "receipts"
    corpus = tmp_path / "corpus"
    _write_registry(registry_root)
    _write_artifact(registry_root=registry_root, artifacts_root=artifacts_root)

    report = assemble(
        registry_root=registry_root,
        artifacts_root=artifacts_root,
        workspace_root=workspace,
        receipts_dir=receipts,
    )
    assert report["structural_integrity_pass"] is True
    assert report["valid_operator_receipts"] == 1
    assert report["terminal_state_counts"] == {"RECEIPTED_POSITIVE": 1}

    manifest = build_operator_corpus(
        root=registry_root,
        evidence_root=workspace,
        receipts_dir=receipts,
        corpus_root=corpus,
    )
    assert manifest["snapshot"]["processed_inventory_complete"] is True

    verification = verify_operator_corpus(
        root=registry_root,
        operator_root=workspace,
        corpus_root=corpus,
    )
    assert verification["verified"] is True
    assert verification["operator_corpus_authoritative"] is True


def test_duplicate_source_artifact_fails_structural_integrity(tmp_path: Path) -> None:
    registry_root = tmp_path / "registry"
    artifacts_root = tmp_path / "artifacts"
    _write_registry(registry_root)
    _write_artifact(
        registry_root=registry_root,
        artifacts_root=artifacts_root,
        artifact_name="keyless-alpha-a",
        value="one",
    )
    _write_artifact(
        registry_root=registry_root,
        artifacts_root=artifacts_root,
        artifact_name="keyless-alpha-b",
        value="two",
    )

    report = assemble(
        registry_root=registry_root,
        artifacts_root=artifacts_root,
        workspace_root=tmp_path / "workspace",
        receipts_dir=tmp_path / "receipts",
    )
    assert report["structural_integrity_pass"] is False
    assert "duplicate_source_artifact:alpha" in report["structural_errors"]
