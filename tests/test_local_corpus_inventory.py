from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from moneysweep.orchestrator import offline_baseline as baseline


def test_inventory_preserves_files_hashes_and_fails_closed_on_rows(tmp_path: Path) -> None:
    corpus = tmp_path / "operator" / "financial"
    corpus.mkdir(parents=True)
    (corpus / "contracts.pdf").write_bytes(b"%PDF-1.7\nnot-a-real-pdf-fixture")
    (corpus / "control.txt").write_text("DELTA_ONLY_MODE", encoding="utf-8")

    bindings = {
        "contracts.pdf": {
            "source_ids": ["act_transition_contracts"],
            "semantic_class": "CONTRACT_REGISTER",
            "evidence_class": "financial",
        },
        "control.txt": {
            "source_ids": [],
            "semantic_class": "WORKFLOW_CONTROL",
            "evidence_class": "control",
        },
    }
    manifest = baseline._inventory_local_corpus(
        baseline._LocalCorpusConfig(
            input_dir=corpus,
            bindings=bindings,
            generated_at="2026-08-24T12:00:00+00:00",
        )
    )

    assert manifest["file_count"] == 2
    assert manifest["financial_file_count"] == 1
    assert manifest["control_file_count"] == 1
    assert manifest["unresolved_file_count"] == 0
    assert manifest["certification"]["file_conservation"] == "PASS"
    assert manifest["certification"]["record_conservation"] == "OPEN"
    assert manifest["certification"]["queryable_evidence"] is False
    assert all(item["queryable"] is False for item in manifest["files"])
    text = json.dumps(manifest)
    assert str(tmp_path) not in text


def test_inventory_same_filename_different_bytes_is_not_identity(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    (corpus / "a").mkdir(parents=True)
    (corpus / "b").mkdir(parents=True)
    (corpus / "a" / "same.pdf").write_bytes(b"%PDF-1.4\nA")
    (corpus / "b" / "same.pdf").write_bytes(b"%PDF-1.4\nB")

    manifest = baseline._inventory_local_corpus(baseline._LocalCorpusConfig(input_dir=corpus))
    hashes = {item["sha256"] for item in manifest["files"]}

    assert len(hashes) == 2
    assert manifest["duplicate_byte_group_count"] == 0


def test_inventory_marks_byte_identical_files_without_dropping_rows(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    payload = b"%PDF-1.4\nidentical"
    (corpus / "one.pdf").write_bytes(payload)
    (corpus / "two.pdf").write_bytes(payload)

    manifest = baseline._inventory_local_corpus(baseline._LocalCorpusConfig(input_dir=corpus))

    assert manifest["file_count"] == 2
    assert manifest["duplicate_byte_group_count"] == 1
    assert manifest["byte_duplicate_groups"][0]["classification"] == "BYTE_IDENTICAL"
    assert len(manifest["byte_duplicate_groups"][0]["paths"]) == 2


def test_inventory_rejects_symlink_escape(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    outside = tmp_path / "outside.pdf"
    outside.write_bytes(b"%PDF-1.4\noutside")
    link = corpus / "escape.pdf"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")

    manifest = baseline._inventory_local_corpus(baseline._LocalCorpusConfig(input_dir=corpus))

    assert manifest["file_count"] == 0
    assert manifest["excluded_path_count"] == 1
    assert manifest["excluded_paths"][0]["reason"] == "SYMLINK_REJECTED"


def test_archive_members_have_path_size_and_sha256(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    workbook = corpus / "sample.xlsx"
    with zipfile.ZipFile(workbook, "w") as archive:
        archive.writestr("xl/sharedStrings.xml", b"alpha")
        archive.writestr("xl/worksheets/sheet1.xml", b"beta")

    manifest = baseline._inventory_local_corpus(baseline._LocalCorpusConfig(input_dir=corpus))
    members = manifest["files"][0]["archive_members"]

    assert [member["path"] for member in members] == [
        "xl/sharedStrings.xml",
        "xl/worksheets/sheet1.xml",
    ]
    assert all(member["uncompressed_size"] > 0 for member in members)
    assert all(len(member["sha256"]) == 64 for member in members)


def test_inventory_rejects_unknown_registry_binding(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "contracts.pdf").write_bytes(b"%PDF-1.4\nfixture")

    with pytest.raises(baseline.OfflineBaselineViolation, match="unknown source_ids"):
        baseline._inventory_local_corpus(
            baseline._LocalCorpusConfig(
                input_dir=corpus,
                bindings={
                    "contracts.pdf": {
                        "source_ids": ["definitely_not_a_real_source_id"],
                        "semantic_class": "CONTRACT_REGISTER",
                        "evidence_class": "financial",
                    }
                },
            )
        )


def test_inventory_rejects_receipt_inside_corpus(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "contracts.pdf").write_bytes(b"%PDF-1.4\nfixture")

    with pytest.raises(baseline.OfflineBaselineViolation, match="outside the inventoried root"):
        baseline._inventory_local_corpus(
            baseline._LocalCorpusConfig(
                input_dir=corpus,
                output_path=corpus / "local_corpus_manifest.json",
            )
        )


def test_record_conservation_requires_arithmetic_and_provenance_closure() -> None:
    passed = baseline._certify_record_conservation(
        source_records=10,
        retained_records=8,
        excluded_records=2,
        unresolved_records=0,
        provenance_complete_records=10,
    )
    assert passed["state"] == "PASS"
    assert passed["queryable"] is True

    lost = baseline._certify_record_conservation(
        source_records=10,
        retained_records=8,
        excluded_records=1,
        unresolved_records=0,
        provenance_complete_records=10,
    )
    assert lost["state"] == "FAIL"
    assert lost["arithmetic_closed"] is False
    assert lost["queryable"] is False

    provenance_gap = baseline._certify_record_conservation(
        source_records=10,
        retained_records=8,
        excluded_records=2,
        unresolved_records=0,
        provenance_complete_records=9,
    )
    assert provenance_gap["state"] == "FAIL"
    assert provenance_gap["provenance_closed"] is False
    assert provenance_gap["queryable"] is False

    unresolved = baseline._certify_record_conservation(
        source_records=10,
        retained_records=8,
        excluded_records=2,
        unresolved_records=1,
        provenance_complete_records=10,
    )
    assert unresolved["state"] == "FAIL"
    assert unresolved["queryable"] is False


def test_record_conservation_rejects_negative_counts() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        baseline._certify_record_conservation(
            source_records=1,
            retained_records=-1,
            excluded_records=2,
            unresolved_records=0,
            provenance_complete_records=1,
        )
