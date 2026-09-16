from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
import yaml

from tools.assemble_keyless_operator_workspace import assemble
from tools.certification_truth_guards import digest_json
from tools.operator_corpus_common import (
    load_sources,
    source_definition_digest,
    source_ids_digest,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source(source_id: str, rel: str, *, min_rows: int = 1) -> dict:
    return {
        "source_id": source_id,
        "family": "test",
        "required": False,
        "authentication": "none",
        "producer_script": f"scripts/{source_id}.py",
        "expected_outputs": [rel],
        "validation_threshold": {"min_rows": min_rows},
        "update_cadence": "weekly",
    }


def _registry(root: Path, sources: list[dict]) -> None:
    directory = root / "registries"
    directory.mkdir(parents=True)
    payload = {"schema_version": "test_v1", "sources": sources}
    (directory / "source_registry.yaml").write_text(
        yaml.safe_dump(payload, sort_keys=False), encoding="utf-8"
    )
    (directory / "source_registry.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _write_bundle(
    artifacts_root: Path,
    registry_root: Path,
    *,
    source_id: str,
    rel: str,
    rows: int,
    status: str,
    registry_digest: str | None = None,
    definition_digest: str | None = None,
    producer: str | None = None,
    execution_expected: list[str] | None = None,
    workflow_outcome: str = "success",
    missing_expected: list[str] | None = None,
    coverage_contract_pass: bool = False,
) -> None:
    sources, _ = load_sources(registry_root)
    source_by_id = {str(source["source_id"]): source for source in sources}
    source = source_by_id[source_id]
    current_registry_digest = source_ids_digest(sources)
    producer_sha = "a" * 40
    started_at = "2026-09-01T00:00:00+00:00"
    completed_at = "2026-09-01T00:01:00+00:00"

    bundle = artifacts_root / f"keyless-{source_id}"
    artifact = bundle / "files" / rel
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text("value\n" + "x\n" * rows, encoding="utf-8")
    digest = _sha256(artifact)
    size = artifact.stat().st_size

    receipt = {
        "schema_version": "moneysweep.operator_evidence/v1",
        "source_id": source_id,
        "acquisition": {
            "producer": producer or source["producer_script"],
            "producer_sha": producer_sha,
            "started_at": started_at,
            "completed_at": completed_at,
            "source_url": f"https://example.test/{source_id}",
            "http_status": 200,
        },
        "registry": {
            "source_ids_sha256": registry_digest or current_registry_digest,
            "source_definition_sha256": definition_digest or source_definition_digest(source),
        },
        "outputs": [
            {
                "path": rel,
                "sha256": digest,
                "bytes": size,
                "rows": rows,
                "content_type": "text/csv",
            }
        ],
        "validation": {
            "schema_valid": True,
            "positive_rows": rows > 0,
            "coverage_contract_pass": coverage_contract_pass,
        },
    }
    receipt_path = bundle / "operator_evidence" / f"{source_id}.json"
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

    execution = {
        "schema_version": "moneysweep.keyless_execution/v2",
        "source_id": source_id,
        "certification_implementation_sha": producer_sha,
        "source_ids_sha256": current_registry_digest,
        "started_at": started_at,
        "completed_at": completed_at,
        "workflow_step_outcome": workflow_outcome,
        "expected_outputs": execution_expected if execution_expected is not None else [rel],
        "missing_expected_outputs": missing_expected or [],
        "declared_files": [{"path": rel, "sha256": digest, "bytes": size}],
        "standardized_receipt_emitted": True,
        "standardized_receipt_error": None,
        "runner_summary": {
            "status": "OK",
            "ran": [{"source": source_id, "status": status, "rows": rows}],
        },
    }
    (bundle / "execution_receipt.json").write_text(json.dumps(execution), encoding="utf-8")


def test_assembly_preserves_zero_row_blocker_without_asserting_authority(tmp_path: Path) -> None:
    registry = tmp_path / "repo"
    rel = "data/staging/processed/pr_cor3_projects.csv"
    _registry(registry, [_source("cor3", rel)])
    artifacts = tmp_path / "artifacts"
    _write_bundle(
        artifacts,
        registry,
        source_id="cor3",
        rel=rel,
        rows=0,
        status="EMPTY",
    )

    workspace = tmp_path / "workspace"
    manifest = assemble(
        artifacts_root=artifacts,
        workspace_root=workspace,
        registry_root=registry,
        expected_keyless_count=1,
    )

    assert manifest["artifact_source_count"] == 1
    assert manifest["valid_receipt_count"] == 1
    assert manifest["canonical_execution_count"] == 1
    assert manifest["positive_row_source_count"] == 0
    assert manifest["authority_asserted"] is False
    assert "cor3:nonpositive_or_unproven_rows" in manifest["blockers"]
    assert manifest["policy"]["receipt_source_definition_binding_required"] is True
    assert (workspace / "receipts" / "cor3.json").is_file()
    assert (workspace / rel).is_file()

    receipt = json.loads((workspace / "receipts" / "cor3.json").read_text(encoding="utf-8"))
    execution = json.loads(
        (workspace / "execution_receipts" / "cor3.json").read_text(encoding="utf-8")
    )
    assert execution["schema_version"] == "moneysweep.source_execution/v1"
    assert execution["evidence_receipt_sha256"] == digest_json(receipt)
    assert execution["producer_git_sha"] == receipt["acquisition"]["producer_sha"]
    assert execution["started_at"] == receipt["acquisition"]["started_at"]
    assert execution["completed_at"] == receipt["acquisition"]["completed_at"]
    assert execution["execution_status"] == "SUCCESS"


def test_zero_rows_can_be_accepted_only_by_proven_contract(tmp_path: Path) -> None:
    registry = tmp_path / "repo"
    rel = "data/staging/processed/zero_allowed.csv"
    _registry(registry, [_source("zero_allowed", rel, min_rows=0)])
    artifacts = tmp_path / "artifacts"
    _write_bundle(
        artifacts,
        registry,
        source_id="zero_allowed",
        rel=rel,
        rows=0,
        status="OK",
        coverage_contract_pass=True,
    )

    manifest = assemble(
        artifacts_root=artifacts,
        workspace_root=tmp_path / "workspace",
        registry_root=registry,
        expected_keyless_count=1,
    )
    row = manifest["sources"][0]
    assert row["positive_rows"] is False
    assert row["coverage_contract_pass"] is True
    assert row["row_evidence_acceptable"] is True
    assert "zero_allowed:nonpositive_or_unproven_rows" not in manifest["blockers"]


def test_assembly_rejects_ambiguous_cross_source_output_claim(tmp_path: Path) -> None:
    registry = tmp_path / "repo"
    rel = "data/staging/processed/shared.csv"
    _registry(registry, [_source("source_a", rel), _source("source_b", rel)])
    artifacts = tmp_path / "artifacts"
    _write_bundle(artifacts, registry, source_id="source_a", rel=rel, rows=1, status="OK")
    _write_bundle(artifacts, registry, source_id="source_b", rel=rel, rows=1, status="OK")

    with pytest.raises(RuntimeError, match="ambiguous cross-source output claim"):
        assemble(
            artifacts_root=artifacts,
            workspace_root=tmp_path / "workspace",
            registry_root=registry,
            expected_keyless_count=2,
        )


def test_assembly_requires_complete_expected_artifact_count(tmp_path: Path) -> None:
    registry = tmp_path / "repo"
    rel = "data/staging/processed/source_a.csv"
    _registry(registry, [_source("source_a", rel)])
    artifacts = tmp_path / "artifacts"
    _write_bundle(artifacts, registry, source_id="source_a", rel=rel, rows=1, status="OK")

    with pytest.raises(RuntimeError, match="keyless artifact count mismatch"):
        assemble(
            artifacts_root=artifacts,
            workspace_root=tmp_path / "workspace",
            registry_root=registry,
            expected_keyless_count=2,
        )


@pytest.mark.parametrize(
    ("kwargs", "expected_error"),
    [
        ({"registry_digest": "f" * 64}, "receipt_registry_digest_mismatch"),
        ({"definition_digest": "e" * 64}, "receipt_source_definition_digest_mismatch"),
        ({"producer": "scripts/old_source_a.py"}, "receipt_producer_mismatch"),
        ({"execution_expected": ["data/staging/processed/old.csv"]}, "execution_expected_outputs_registry_mismatch"),
    ],
)
def test_stale_or_misbound_receipt_is_not_promoted(
    tmp_path: Path, kwargs: dict, expected_error: str
) -> None:
    registry = tmp_path / "repo"
    rel = "data/staging/processed/source_a.csv"
    _registry(registry, [_source("source_a", rel)])
    artifacts = tmp_path / "artifacts"
    _write_bundle(
        artifacts,
        registry,
        source_id="source_a",
        rel=rel,
        rows=1,
        status="OK",
        **kwargs,
    )

    workspace = tmp_path / "workspace"
    manifest = assemble(
        artifacts_root=artifacts,
        workspace_root=workspace,
        registry_root=registry,
        expected_keyless_count=1,
    )

    row = manifest["sources"][0]
    assert row["standardized_receipt_valid"] is False
    assert row["canonical_execution_emitted"] is False
    assert expected_error in row["receipt_errors"]
    assert row["promoted_workspace_files"] == []
    assert not (workspace / rel).exists()
    assert "source_a:standardized_receipt_invalid_or_missing" in manifest["blockers"]


@pytest.mark.parametrize(
    ("workflow_outcome", "missing_expected", "expected_error"),
    [
        ("failure", [], "execution_workflow_step_not_success"),
        ("success", ["data/staging/processed/source_a.csv"], "execution_missing_expected_outputs"),
    ],
)
def test_failed_or_incomplete_execution_cannot_promote_stale_output(
    tmp_path: Path,
    workflow_outcome: str,
    missing_expected: list[str],
    expected_error: str,
) -> None:
    registry = tmp_path / "repo"
    rel = "data/staging/processed/source_a.csv"
    _registry(registry, [_source("source_a", rel)])
    artifacts = tmp_path / "artifacts"
    _write_bundle(
        artifacts,
        registry,
        source_id="source_a",
        rel=rel,
        rows=1,
        status="OK",
        workflow_outcome=workflow_outcome,
        missing_expected=missing_expected,
    )

    workspace = tmp_path / "workspace"
    manifest = assemble(
        artifacts_root=artifacts,
        workspace_root=workspace,
        registry_root=registry,
        expected_keyless_count=1,
    )
    row = manifest["sources"][0]
    assert row["standardized_receipt_valid"] is False
    assert expected_error in row["receipt_errors"]
    assert row["canonical_execution_emitted"] is False
    assert row["promoted_workspace_files"] == []
    assert not (workspace / rel).exists()


def test_unknown_source_id_fails_closed(tmp_path: Path) -> None:
    registry = tmp_path / "repo"
    rel = "data/staging/processed/source_a.csv"
    _registry(registry, [_source("source_a", rel)])
    artifacts = tmp_path / "artifacts"
    _write_bundle(artifacts, registry, source_id="source_a", rel=rel, rows=1, status="OK")
    execution = artifacts / "keyless-source_a" / "execution_receipt.json"
    payload = json.loads(execution.read_text(encoding="utf-8"))
    payload["source_id"] = "retired_source"
    execution.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(RuntimeError, match="unknown keyless source_id"):
        assemble(
            artifacts_root=artifacts,
            workspace_root=tmp_path / "workspace",
            registry_root=registry,
            expected_keyless_count=1,
        )
