from __future__ import annotations

from pathlib import Path

import pytest

import tools.certification_operator_lineage as lineage

pytestmark = pytest.mark.unit

DIGEST = "d" * 64
CORPUS_ID = "c" * 64


def _scope(corpus_id: str | None = CORPUS_ID) -> dict:
    return {"scope_identity": {"operator_corpus_id": corpus_id}}


def _verification(**overrides: object) -> dict:
    payload = {
        "verified": True,
        "operator_corpus_authoritative": True,
        "corpus_id": CORPUS_ID,
        "computed_corpus_id": CORPUS_ID,
        "verification_scope": {
            "operator_snapshot_required": True,
            "mode": "full_operator_snapshot",
        },
        "registry": {
            "total_sources": 164,
            "source_ids_sha256": DIGEST,
        },
        "manifest_source_count": 164,
        "manifest_product_count": 3,
        "processed_file_inventory": {
            "orphan_mounted_files": [],
            "unreceipted_operator_files": [],
            "accounted_outputs_missing_from_operator": [],
        },
        "errors": [],
    }
    payload.update(overrides)
    return payload


def test_missing_corpus_root_never_grants_authority(tmp_path: Path) -> None:
    result = lineage.verify_scope_bound_operator_corpus(
        root=tmp_path,
        corpus_root=None,
        truth_scope=_scope(),
        current_registry_total=164,
        current_registry_digest=DIGEST,
    )

    assert result["authoritative"] is False
    assert "operator_corpus_root_not_supplied" in result["blockers"]


def test_stored_or_claimed_corpus_id_without_truth_scope_never_grants_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(lineage, "verify_operator_corpus", lambda **_: _verification())

    result = lineage.verify_scope_bound_operator_corpus(
        root=tmp_path,
        corpus_root=tmp_path / "corpus",
        truth_scope=None,
        current_registry_total=164,
        current_registry_digest=DIGEST,
    )

    assert result["authoritative"] is False
    assert "truth_scope_required_for_operator_corpus" in result["blockers"]
    assert "truth_scope_operator_corpus_id_missing" in result["blockers"]


def test_content_only_revalidation_cannot_grant_full_snapshot_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        lineage,
        "verify_operator_corpus",
        lambda **_: _verification(
            verification_scope={
                "operator_snapshot_required": False,
                "mode": "content_revalidation",
            },
            operator_corpus_authoritative=False,
        ),
    )

    result = lineage.verify_scope_bound_operator_corpus(
        root=tmp_path,
        corpus_root=tmp_path / "corpus",
        truth_scope=_scope(),
        current_registry_total=164,
        current_registry_digest=DIGEST,
    )

    assert result["authoritative"] is False
    assert "operator_corpus_not_full_snapshot_verification" in result["blockers"]
    assert "operator_corpus_verification_mode_mismatch" in result["blockers"]
    assert "operator_corpus_authority_not_proven" in result["blockers"]


def test_scope_corpus_identity_mismatch_blocks_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(lineage, "verify_operator_corpus", lambda **_: _verification())

    result = lineage.verify_scope_bound_operator_corpus(
        root=tmp_path,
        corpus_root=tmp_path / "corpus",
        truth_scope=_scope("e" * 64),
        current_registry_total=164,
        current_registry_digest=DIGEST,
    )

    assert result["authoritative"] is False
    assert "truth_scope_operator_corpus_id_mismatch" in result["blockers"]


def test_registry_digest_or_denominator_mismatch_blocks_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        lineage,
        "verify_operator_corpus",
        lambda **_: _verification(
            registry={"total_sources": 162, "source_ids_sha256": "a" * 64},
            manifest_source_count=162,
        ),
    )

    result = lineage.verify_scope_bound_operator_corpus(
        root=tmp_path,
        corpus_root=tmp_path / "corpus",
        truth_scope=_scope(),
        current_registry_total=164,
        current_registry_digest=DIGEST,
    )

    assert result["authoritative"] is False
    assert "operator_corpus_registry_total_mismatch" in result["blockers"]
    assert "operator_corpus_registry_digest_mismatch" in result["blockers"]
    assert "operator_corpus_manifest_source_count_mismatch" in result["blockers"]


def test_unreceipted_or_orphan_processed_files_block_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        lineage,
        "verify_operator_corpus",
        lambda **_: _verification(
            processed_file_inventory={
                "orphan_mounted_files": ["data/staging/processed/orphan.csv"],
                "unreceipted_operator_files": ["data/staging/processed/unreceipted.csv"],
                "accounted_outputs_missing_from_operator": [
                    "data/staging/processed/missing.csv"
                ],
            }
        ),
    )

    result = lineage.verify_scope_bound_operator_corpus(
        root=tmp_path,
        corpus_root=tmp_path / "corpus",
        truth_scope=_scope(),
        current_registry_total=164,
        current_registry_digest=DIGEST,
    )

    assert result["authoritative"] is False
    assert "operator_corpus_orphan_mounted_files" in result["blockers"]
    assert "operator_corpus_unreceipted_operator_files" in result["blockers"]
    assert "operator_corpus_accounted_outputs_missing_from_operator" in result["blockers"]


def test_missing_inventory_fields_and_errors_list_block_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        lineage,
        "verify_operator_corpus",
        lambda **_: _verification(
            processed_file_inventory={},
            errors=None,
        ),
    )

    result = lineage.verify_scope_bound_operator_corpus(
        root=tmp_path,
        corpus_root=tmp_path / "corpus",
        truth_scope=_scope(),
        current_registry_total=164,
        current_registry_digest=DIGEST,
    )

    assert result["authoritative"] is False
    assert (
        "operator_corpus_inventory_orphan_mounted_files_missing_or_invalid"
        in result["blockers"]
    )
    assert (
        "operator_corpus_inventory_unreceipted_operator_files_missing_or_invalid"
        in result["blockers"]
    )
    assert (
        "operator_corpus_inventory_accounted_outputs_missing_from_operator_missing_or_invalid"
        in result["blockers"]
    )
    assert "operator_corpus_verification_errors_missing_or_invalid" in result["blockers"]


def test_only_fresh_full_snapshot_scope_bound_verification_grants_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []

    def fake_verify(**kwargs: object) -> dict:
        calls.append(kwargs)
        return _verification()

    monkeypatch.setattr(lineage, "verify_operator_corpus", fake_verify)

    result = lineage.verify_scope_bound_operator_corpus(
        root=tmp_path,
        corpus_root=tmp_path / "corpus",
        truth_scope=_scope(),
        current_registry_total=164,
        current_registry_digest=DIGEST,
    )

    assert result["authoritative"] is True
    assert result["blockers"] == []
    assert calls[0]["require_operator_snapshot"] is True
    assert result["corpus_id"] == CORPUS_ID
    assert result["registry"] == {
        "total_sources": 164,
        "source_ids_sha256": DIGEST,
    }