from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
import yaml

from tools.verify_source_equivalence import verify

pytestmark = pytest.mark.unit


def _root(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    directory = root / "registries"
    directory.mkdir(parents=True)
    payload = {
        "schema_version": "test_v1",
        "sources": [
            {
                "source_id": "alpha",
                "family": "test",
                "required": True,
                "authentication": "none",
                "producer_script": "scripts/alpha.py",
                "expected_outputs": ["data/original.csv"],
                "validation_threshold": {"min_rows": 1},
            }
        ],
    }
    (directory / "source_registry.yaml").write_text(
        yaml.safe_dump(payload, sort_keys=False), encoding="utf-8"
    )
    (directory / "source_registry.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return root


def _claim() -> dict:
    return {
        "schema_version": "moneysweep.source_equivalence/v2",
        "source_id": "alpha",
        "candidate_source": {
            "name": "Authoritative replacement",
            "source_url": "https://example.invalid/alpha",
            "authoritative": True,
        },
        "tests": {
            "semantic_scope_match": True,
            "temporal_scope_match": True,
            "selection_equivalent": True,
            "aggregation_equivalent": True,
        },
        "comparison": {
            "original_path": "data/original.csv",
            "candidate_path": "data/candidate.csv",
            "original_sha256": "0" * 64,
            "candidate_sha256": "0" * 64,
            "original_format": {"encoding": "utf-8", "delimiter": ",", "header_row": 1},
            "candidate_format": {"encoding": "utf-8", "delimiter": ",", "header_row": 1},
            "stable_key": ["id"],
            "compare_fields": ["id", "name", "amount"],
            "field_mapping": {"id": "record_id", "name": "label", "amount": "value"},
        },
        "missing_fields": [],
        "extra_fields": [],
        "evidence": [
            {
                "kind": "comparison_manifest",
                "locator": "reports/alpha_equivalence.json",
                "sha256": "0" * 64,
            }
        ],
    }


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _materialize(
    root: Path,
    claim: dict,
    *,
    original: str = "id,name,amount\n1,A,10\n2,B,20\n",
    candidate: str = "record_id,label,value\n1,A,10\n2,B,20\n",
) -> None:
    data = root / "data"
    reports = root / "reports"
    data.mkdir(parents=True, exist_ok=True)
    reports.mkdir(parents=True, exist_ok=True)
    original_path = data / "original.csv"
    candidate_path = data / "candidate.csv"
    original_path.write_text(original, encoding="utf-8")
    candidate_path.write_text(candidate, encoding="utf-8")
    claim["comparison"]["original_sha256"] = _sha(original_path)
    claim["comparison"]["candidate_sha256"] = _sha(candidate_path)
    evidence_path = reports / "alpha_equivalence.json"
    evidence_path.write_text('{"claim":"alpha","scope":"bounded"}\n', encoding="utf-8")
    claim["evidence"][0]["sha256"] = _sha(evidence_path)


def test_complete_computed_equivalence_can_certify(tmp_path: Path) -> None:
    root = _root(tmp_path)
    claim = _claim()
    _materialize(root, claim)

    report = verify(root=root, claim=claim)

    assert report["certified_equivalent"] is True
    assert report["decision"] == "CERTIFIED_EQUIVALENT"
    assert report["blockers"] == []
    arithmetic = report["comparison"]["set_arithmetic"]
    assert arithmetic["INTERSECTION"] == 2
    assert arithmetic["A_ONLY"] == 0
    assert arithmetic["B_ONLY"] == 0
    assert arithmetic["UNION"] == 2
    assert arithmetic["SYMMETRIC_DIFFERENCE"] == 0
    assert report["comparison"]["projection_difference_count"] == 0
    assert report["policy"]["normalization_can_prove_identity"] is False


def test_row_universe_difference_is_preserved_not_papered_over(tmp_path: Path) -> None:
    root = _root(tmp_path)
    claim = _claim()
    _materialize(
        root,
        claim,
        candidate="record_id,label,value\n1,A,10\n3,C,30\n",
    )

    report = verify(root=root, claim=claim)

    assert report["certified_equivalent"] is False
    assert report["decision"] == "PARTIAL_EQUIVALENCE"
    arithmetic = report["comparison"]["set_arithmetic"]
    assert arithmetic["INTERSECTION"] == 1
    assert arithmetic["A_ONLY"] == 1
    assert arithmetic["B_ONLY"] == 1
    assert arithmetic["UNION"] == 3
    assert arithmetic["SYMMETRIC_DIFFERENCE"] == 2
    assert arithmetic["a_only_keys"] == [{"id": "2"}]
    assert arithmetic["b_only_keys"] == [{"id": "3"}]
    assert "row_universe_mismatch" in report["blockers"]


def test_same_keys_but_different_whole_row_projection_is_partial(tmp_path: Path) -> None:
    root = _root(tmp_path)
    claim = _claim()
    _materialize(
        root,
        claim,
        candidate="record_id,label,value\n1,A,10\n2,B,999\n",
    )

    report = verify(root=root, claim=claim)

    assert report["decision"] == "PARTIAL_EQUIVALENCE"
    assert report["comparison"]["set_arithmetic"]["SYMMETRIC_DIFFERENCE"] == 0
    assert report["comparison"]["projection_difference_count"] == 1
    diff = report["comparison"]["projection_differences"][0]
    assert diff["key"] == {"id": "2"}
    assert diff["original"]["amount"] == "20"
    assert diff["candidate_mapped"]["amount"] == "999"
    assert "row_projection_mismatch" in report["blockers"]


def test_duplicate_stable_keys_fail_closed_without_whole_row_selection(tmp_path: Path) -> None:
    root = _root(tmp_path)
    claim = _claim()
    _materialize(
        root,
        claim,
        original="id,name,amount\n1,A,10\n1,A2,11\n",
        candidate="record_id,label,value\n1,A,10\n",
    )

    report = verify(root=root, claim=claim)

    assert report["certified_equivalent"] is False
    assert report["comparison"]["original_duplicate_keys"] == [{"id": "1"}]
    assert "comparison_execution_failed" in report["blockers"]
    assert "row_universe_mismatch" in report["blockers"]


def test_explicit_header_row_is_honored(tmp_path: Path) -> None:
    root = _root(tmp_path)
    claim = _claim()
    claim["comparison"]["original_format"]["header_row"] = 2
    claim["comparison"]["candidate_format"]["header_row"] = 2
    _materialize(
        root,
        claim,
        original="metadata,alpha\nid,name,amount\n1,A,10\n2,B,20\n",
        candidate="metadata,beta\nrecord_id,label,value\n1,A,10\n2,B,20\n",
    )

    report = verify(root=root, claim=claim)

    assert report["certified_equivalent"] is True
    assert report["comparison"]["original"]["preamble_rows"] == 1
    assert report["comparison"]["candidate"]["preamble_rows"] == 1


def test_missing_fields_prevent_certified_equivalence(tmp_path: Path) -> None:
    root = _root(tmp_path)
    claim = _claim()
    _materialize(root, claim)
    claim["missing_fields"] = ["award_amount"]

    report = verify(root=root, claim=claim)

    assert report["certified_equivalent"] is False
    assert "missing_fields_present" in report["blockers"]


def test_authoritative_candidate_is_required(tmp_path: Path) -> None:
    root = _root(tmp_path)
    claim = _claim()
    _materialize(root, claim)
    claim["candidate_source"]["authoritative"] = False

    report = verify(root=root, claim=claim)

    assert report["certified_equivalent"] is False
    assert "candidate_not_authoritative" in report["blockers"]


def test_declared_scope_contradiction_classifies_non_equivalent(tmp_path: Path) -> None:
    root = _root(tmp_path)
    claim = _claim()
    _materialize(root, claim)
    claim["tests"]["selection_equivalent"] = False

    report = verify(root=root, claim=claim)

    assert report["certified_equivalent"] is False
    assert report["decision"] == "NON_EQUIVALENT"
    assert "selection_equivalent" in report["blockers"]


def test_tampered_comparison_bytes_fail_closed(tmp_path: Path) -> None:
    root = _root(tmp_path)
    claim = _claim()
    _materialize(root, claim)
    (root / "data" / "candidate.csv").write_text(
        "record_id,label,value\n1,A,10\n2,B,21\n", encoding="utf-8"
    )

    report = verify(root=root, claim=claim)

    assert report["certified_equivalent"] is False
    assert "comparison_execution_failed" in report["blockers"]
    assert "candidate_sha256_mismatch" in report["comparison"]["errors"]


def test_missing_evidence_file_fails_closed(tmp_path: Path) -> None:
    root = _root(tmp_path)
    claim = _claim()
    _materialize(root, claim)
    (root / "reports" / "alpha_equivalence.json").unlink()

    report = verify(root=root, claim=claim)

    assert report["certified_equivalent"] is False
    assert "evidence_not_byte_verified" in report["blockers"]
    assert "evidence_file_missing" in report["evidence_blockers"]


def test_remote_only_evidence_cannot_certify(tmp_path: Path) -> None:
    root = _root(tmp_path)
    claim = _claim()
    _materialize(root, claim)
    claim["evidence"][0]["locator"] = "https://example.invalid/evidence.json"

    report = verify(root=root, claim=claim)

    assert report["certified_equivalent"] is False
    assert "evidence_not_byte_verified" in report["blockers"]
    assert "remote_evidence_not_byte_verified" in report["evidence_blockers"]
