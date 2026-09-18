from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from tools.audit_materialization_coverage import build as build_coverage_audit
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


def _source(source_id: str, outputs: list[str]) -> dict:
    return {
        "source_id": source_id,
        "family": "test",
        "required": True,
        "authentication": "none",
        "producer_script": f"scripts/{source_id}.py",
        "expected_outputs": outputs,
        "schema_version": "test_v1",
        "validation_threshold": {"min_rows": 1},
        "update_cadence": "daily",
    }


def _write_registry(root: Path, source: dict) -> None:
    registry_dir = root / "registries"
    registry_dir.mkdir(parents=True)
    (registry_dir / "source_registry.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": "test_source_registry_v1",
                "sources": [source],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def _write_csv(root: Path, rel: str, rows: list[tuple[str, str]]) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["id,value", *[f"{left},{right}" for left, right in rows]]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _write_receipt(
    root: Path,
    receipts: Path,
    source: dict,
    output_paths: list[str],
) -> Path:
    sources, _ = load_sources(root)
    receipt = {
        "schema_version": "moneysweep.operator_evidence/v1",
        "source_id": source["source_id"],
        "acquisition": {
            "producer": source["producer_script"],
            "producer_sha": "a" * 40,
            "started_at": "2026-08-29T10:00:00-04:00",
            "completed_at": "2026-08-29T10:01:00-04:00",
            "source_url": "https://example.invalid/authoritative",
            "http_status": 200,
        },
        "registry": {
            "source_ids_sha256": source_ids_digest(sources),
            "source_definition_sha256": source_definition_digest(source),
        },
        "outputs": [],
        "validation": {
            "schema_valid": True,
            "positive_rows": True,
            "coverage_contract_pass": True,
        },
    }
    for rel in output_paths:
        path = root / rel
        receipt["outputs"].append(
            {
                "path": rel,
                "sha256": sha256_file(path),
                "bytes": path.stat().st_size,
                "rows": csv_rows(path),
                "content_type": "text/csv" if path.suffix == ".csv" else None,
            }
        )
    receipts.mkdir(parents=True, exist_ok=True)
    path = receipts / f"{source['source_id']}.json"
    path.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def _save_verification(path: Path, report: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def test_csv_rows_uses_logical_path_for_extensionless_corpus_object(
    tmp_path: Path,
) -> None:
    object_path = tmp_path / "objects" / "sha256" / "ab" / "cdef"
    object_path.parent.mkdir(parents=True)
    object_path.write_text("id,value\n1,a\n2,b\n", encoding="utf-8")

    assert csv_rows(object_path) is None
    assert csv_rows(object_path, logical_path="data/staging/processed/alpha.csv") == 2


def test_malformed_csv_cannot_enter_operator_corpus(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    rel = "data/staging/processed/alpha.csv"
    source = _source("alpha", [rel])
    _write_registry(root, source)
    malformed = root / rel
    malformed.parent.mkdir(parents=True, exist_ok=True)
    malformed.write_text('id,value\n1,"unterminated\n', encoding="utf-8")
    receipts = root / "receipts"
    _write_receipt(root, receipts, source, [rel])

    with pytest.raises(RuntimeError, match="unreadable CSV for alpha"):
        build_operator_corpus(
            root=root,
            receipts_dir=receipts,
            corpus_root=root / "build" / "operator-corpus",
        )


def test_complete_corpus_is_deterministic_and_unlocks_authoritative_lineage(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    source = _source("alpha", ["data/staging/processed/alpha.csv"])
    _write_registry(root, source)
    _write_csv(
        root,
        "data/staging/processed/alpha.csv",
        [("1", "a"), ("2", "b")],
    )
    receipts = root / "receipts"
    _write_receipt(root, receipts, source, source["expected_outputs"])

    first_root = root / "build" / "corpus-a"
    second_root = root / "build" / "corpus-b"
    first = build_operator_corpus(
        root=root,
        receipts_dir=receipts,
        corpus_root=first_root,
    )
    second = build_operator_corpus(
        root=root,
        receipts_dir=receipts,
        corpus_root=second_root,
    )
    assert first["corpus_id"] == second["corpus_id"]
    assert first["snapshot"]["processed_inventory_complete"] is True

    verification = verify_operator_corpus(root=root, corpus_root=first_root)
    assert verification["verified"] is True, verification["errors"]
    assert verification["operator_corpus_authoritative"] is True
    assert verification["verification_scope"]["mode"] == "full_operator_snapshot"
    verification_path = _save_verification(
        root / "reports" / "operator_corpus_verification.json",
        verification,
    )

    audit = build_coverage_audit(
        root,
        operator_corpus_manifest=first_root / "manifest.json",
        operator_corpus_verification=verification_path,
    )
    assert audit["audit_scope"]["operator_corpus_authoritative"] is True
    assert audit["audit_scope"]["operator_corpus_id"] == first["corpus_id"]
    assert audit["audit_scope"]["authority_blockers"] == []
    assert audit["processed_file_inventory"]["orphan_rows"] == 0
    assert audit["local_truth_summary"]["fully_materialized"] == 1
    assert audit["local_truth_summary"]["required_fully_materialized"] == 1


def test_partial_source_can_have_authoritative_lineage_without_materialization_credit(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    source = _source(
        "alpha",
        [
            "data/staging/processed/alpha.csv",
            "data/staging/processed/alpha_second.csv",
        ],
    )
    _write_registry(root, source)
    _write_csv(root, "data/staging/processed/alpha.csv", [("1", "a")])
    receipts = root / "receipts"
    _write_receipt(root, receipts, source, ["data/staging/processed/alpha.csv"])

    corpus_root = root / "build" / "operator-corpus"
    manifest = build_operator_corpus(
        root=root,
        receipts_dir=receipts,
        corpus_root=corpus_root,
    )
    verification = verify_operator_corpus(root=root, corpus_root=corpus_root)
    assert verification["verified"] is True, verification["errors"]
    assert verification["operator_corpus_authoritative"] is True
    result = verification["sources"][0]
    assert result["missing_expected_outputs"] == ["data/staging/processed/alpha_second.csv"]
    verification_path = _save_verification(
        root / "reports" / "verification.json",
        verification,
    )

    audit = build_coverage_audit(
        root,
        operator_corpus_manifest=corpus_root / "manifest.json",
        operator_corpus_verification=verification_path,
    )
    assert audit["audit_scope"]["operator_corpus_authoritative"] is True
    assert audit["audit_scope"]["operator_corpus_id"] == manifest["corpus_id"]
    assert audit["local_truth_summary"]["partially_materialized"] == 1
    assert audit["local_truth_summary"]["required_fully_materialized"] == 0


def test_unreceipted_operator_processed_file_prevents_authority(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    source = _source("alpha", ["data/staging/processed/alpha.csv"])
    _write_registry(root, source)
    _write_csv(root, "data/staging/processed/alpha.csv", [("1", "a")])
    _write_csv(root, "data/staging/processed/stray.csv", [("9", "orphan")])
    receipts = root / "receipts"
    _write_receipt(root, receipts, source, source["expected_outputs"])

    corpus_root = root / "build" / "operator-corpus"
    manifest = build_operator_corpus(
        root=root,
        receipts_dir=receipts,
        corpus_root=corpus_root,
    )
    assert manifest["snapshot"]["processed_inventory_complete"] is False
    assert manifest["snapshot"]["unreceipted_processed_files"] == [
        "data/staging/processed/stray.csv"
    ]

    verification = verify_operator_corpus(root=root, corpus_root=corpus_root)
    assert verification["verified"] is False
    assert verification["operator_corpus_authoritative"] is False
    assert "processed_inventory_not_complete" in verification["errors"]


def test_post_verification_mount_tamper_is_detected_by_lineage_revalidation(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    rel = "data/staging/processed/alpha.csv"
    source = _source("alpha", [rel])
    _write_registry(root, source)
    _write_csv(root, rel, [("1", "a")])
    receipts = root / "receipts"
    _write_receipt(root, receipts, source, [rel])

    corpus_root = root / "build" / "operator-corpus"
    build_operator_corpus(
        root=root,
        receipts_dir=receipts,
        corpus_root=corpus_root,
    )
    verification = verify_operator_corpus(root=root, corpus_root=corpus_root)
    assert verification["verified"] is True, verification["errors"]
    verification_path = _save_verification(
        root / "reports" / "verification.json",
        verification,
    )

    (corpus_root / "mount" / rel).write_text(
        "id,value\n1,tampered\n",
        encoding="utf-8",
    )
    audit = build_coverage_audit(
        root,
        operator_corpus_manifest=corpus_root / "manifest.json",
        operator_corpus_verification=verification_path,
    )
    assert audit["audit_scope"]["operator_corpus_authoritative"] is False
    assert (
        "operator_corpus_content_revalidation_failed" in audit["audit_scope"]["authority_blockers"]
    )
    assert audit["processed_file_inventory"]["orphan_rows"] is None


def test_receipt_path_traversal_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    source = _source("alpha", ["data/staging/processed/alpha.csv"])
    _write_registry(root, source)
    _write_csv(root, "data/staging/processed/alpha.csv", [("1", "a")])
    receipts = root / "receipts"
    receipt_path = _write_receipt(
        root,
        receipts,
        source,
        source["expected_outputs"],
    )
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["outputs"][0]["path"] = "../outside.csv"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

    with pytest.raises(RuntimeError, match="receipt_output_0_path_unsafe"):
        build_operator_corpus(
            root=root,
            receipts_dir=receipts,
            corpus_root=root / "build" / "operator-corpus",
        )


def test_schema_valid_flag_cannot_hide_invalid_receipt_contract(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    source = _source("alpha", ["data/staging/processed/alpha.csv"])
    _write_registry(root, source)
    _write_csv(root, "data/staging/processed/alpha.csv", [("1", "a")])
    receipts = root / "receipts"
    receipt_path = _write_receipt(
        root,
        receipts,
        source,
        source["expected_outputs"],
    )
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["validation"]["schema_valid"] is True
    receipt["acquisition"]["producer_sha"] = "not-a-git-sha"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

    with pytest.raises(RuntimeError, match="receipt_producer_sha_invalid"):
        build_operator_corpus(
            root=root,
            receipts_dir=receipts,
            corpus_root=root / "build" / "operator-corpus",
        )
