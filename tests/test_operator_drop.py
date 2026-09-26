from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
import yaml

import tools.ingest_operator_drop as drop
from tools.build_operator_corpus import build as build_operator_corpus
from tools.verify_operator_corpus import verify as verify_operator_corpus

pytestmark = pytest.mark.unit


def _registry(root: Path) -> None:
    path = root / "registries/source_registry.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(
        yaml.safe_dump(
            {
                "schema_version": "test_v1",
                "sources": [
                    {
                        "source_id": "alpha",
                        "family": "manual",
                        "required": True,
                        "authentication": "manual_export",
                        "endpoint_url": "https://example.invalid/alpha",
                        "producer_script": "scripts/ingest_alpha.py",
                        "expected_outputs": [
                            "data/staging/processed/alpha.csv"
                        ],
                        "validation_threshold": {"min_rows": 1},
                        "manual_drop_dir": "data/manual/alpha/",
                        "update_cadence": "monthly",
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def _bundle(root: Path, *, tamper_hash: bool = False) -> Path:
    bundle = root / "bundle"
    source = bundle / "files/export.csv"
    source.parent.mkdir(parents=True)
    source.write_text("id,value\n1,official\n", encoding="utf-8")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    if tamper_hash:
        digest = "0" * 64
    manifest = {
        "schema_version": "moneysweep.operator_drop/v1",
        "source_id": "alpha",
        "obtained_at": "2026-09-25T12:00:00+00:00",
        "provenance": {
            "source_url": "https://example.invalid/alpha/export",
            "retrieval_method": "official portal export",
            "snapshot_as_of": "2026-09-25",
            "notes": None,
        },
        "files": [
            {
                "path": "export.csv",
                "sha256": digest,
                "bytes": source.stat().st_size,
            }
        ],
    }
    (bundle / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return bundle


def test_operator_drop_preserves_raw_inputs_through_corpus(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry_root = tmp_path / "registry"
    workspace = tmp_path / "workspace"
    receipts = tmp_path / "receipts"
    corpus = tmp_path / "corpus"
    _registry(registry_root)
    bundle = _bundle(tmp_path)

    monkeypatch.setattr(
        drop,
        "_bind_legacy_config_to_workspace",
        lambda root: {"PROJECT_ROOT": str(root)},
    )

    def fake_run_one(root: Path, source: dict, logger) -> dict:
        assert (root / "data/manual/alpha/export.csv").is_file()
        output = root / "data/staging/processed/alpha.csv"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text("id,value\n1,normalized\n", encoding="utf-8")
        return {
            "source": source["source_id"],
            "producer": source["producer_script"],
            "status": "OK",
            "rows": 1,
            "error": "",
        }

    monkeypatch.setattr(drop, "run_one", fake_run_one)

    report = drop.ingest(
        registry_root=registry_root,
        workspace=workspace,
        bundle_root=bundle,
        receipts_dir=receipts,
        producer_sha="a" * 40,
    )
    assert report["materialization_candidate"] is True
    receipt = json.loads((receipts / "alpha.json").read_text(encoding="utf-8"))
    assert receipt["inputs"][0]["path"] == "data/manual/alpha/export.csv"
    assert receipt["outputs"][0]["path"] == "data/staging/processed/alpha.csv"

    manifest = build_operator_corpus(
        root=registry_root,
        evidence_root=workspace,
        receipts_dir=receipts,
        corpus_root=corpus,
    )
    assert manifest["sources"][0]["inputs"][0]["path"] == (
        "data/manual/alpha/export.csv"
    )
    verification = verify_operator_corpus(
        root=registry_root,
        operator_root=workspace,
        corpus_root=corpus,
    )
    assert verification["verified"] is True
    assert verification["operator_corpus_authoritative"] is True
    assert verification["sources"][0]["input_count"] == 1


def test_operator_drop_rejects_tampered_input_before_ingestion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry_root = tmp_path / "registry"
    workspace = tmp_path / "workspace"
    receipts = tmp_path / "receipts"
    _registry(registry_root)
    bundle = _bundle(tmp_path, tamper_hash=True)
    monkeypatch.setattr(
        drop,
        "_bind_legacy_config_to_workspace",
        lambda root: {"PROJECT_ROOT": str(root)},
    )

    with pytest.raises(RuntimeError, match="sha256 mismatch"):
        drop.ingest(
            registry_root=registry_root,
            workspace=workspace,
            bundle_root=bundle,
            receipts_dir=receipts,
            producer_sha="a" * 40,
        )
