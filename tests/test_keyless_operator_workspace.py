from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from tools.assemble_keyless_operator_workspace import assemble


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_bundle(
    root: Path,
    *,
    source_id: str,
    rel: str,
    rows: int,
    status: str,
) -> None:
    bundle = root / f"keyless-{source_id}"
    artifact = bundle / "files" / rel
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text("value\n" + "x\n" * rows, encoding="utf-8")
    digest = _sha256(artifact)
    size = artifact.stat().st_size

    receipt = {
        "schema_version": "moneysweep.operator_evidence/v1",
        "source_id": source_id,
        "acquisition": {
            "producer": f"scripts/{source_id}.py",
            "producer_sha": "a" * 40,
            "completed_at": "2026-09-01T00:00:00+00:00",
            "source_url": f"https://example.test/{source_id}",
            "http_status": 200,
        },
        "registry": {
            "source_ids_sha256": "b" * 64,
            "source_definition_sha256": "c" * 64,
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
            "coverage_contract_pass": False,
        },
    }
    receipt_path = bundle / "operator_evidence" / f"{source_id}.json"
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

    execution = {
        "schema_version": "moneysweep.keyless_execution/v2",
        "source_id": source_id,
        "workflow_step_outcome": "success",
        "expected_outputs": [rel],
        "missing_expected_outputs": [],
        "declared_files": [{"path": rel, "sha256": digest, "bytes": size}],
        "standardized_receipt_emitted": True,
        "standardized_receipt_error": None,
        "runner_summary": {
            "status": "OK",
            "ran": [
                {
                    "source": source_id,
                    "status": status,
                    "rows": rows,
                }
            ],
        },
    }
    (bundle / "execution_receipt.json").write_text(json.dumps(execution), encoding="utf-8")


def test_assembly_preserves_zero_row_blocker_without_asserting_authority(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    _write_bundle(
        artifacts,
        source_id="cor3",
        rel="data/staging/processed/pr_cor3_projects.csv",
        rows=0,
        status="EMPTY",
    )

    workspace = tmp_path / "workspace"
    manifest = assemble(
        artifacts_root=artifacts,
        workspace_root=workspace,
        expected_keyless_count=1,
    )

    assert manifest["artifact_source_count"] == 1
    assert manifest["valid_receipt_count"] == 1
    assert manifest["positive_row_source_count"] == 0
    assert manifest["authority_asserted"] is False
    assert "cor3:nonpositive_or_unproven_rows" in manifest["blockers"]
    assert (workspace / "receipts" / "cor3.json").is_file()
    assert (workspace / "data/staging/processed/pr_cor3_projects.csv").is_file()


def test_assembly_rejects_ambiguous_cross_source_output_claim(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    rel = "data/staging/processed/shared.csv"
    _write_bundle(artifacts, source_id="source_a", rel=rel, rows=1, status="OK")
    _write_bundle(artifacts, source_id="source_b", rel=rel, rows=1, status="OK")

    with pytest.raises(RuntimeError, match="ambiguous cross-source output claim"):
        assemble(
            artifacts_root=artifacts,
            workspace_root=tmp_path / "workspace",
            expected_keyless_count=2,
        )


def test_assembly_requires_complete_expected_artifact_count(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    _write_bundle(
        artifacts,
        source_id="source_a",
        rel="data/staging/processed/source_a.csv",
        rows=1,
        status="OK",
    )

    with pytest.raises(RuntimeError, match="keyless artifact count mismatch"):
        assemble(
            artifacts_root=artifacts,
            workspace_root=tmp_path / "workspace",
            expected_keyless_count=2,
        )
