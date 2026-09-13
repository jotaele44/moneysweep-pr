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
                "expected_outputs": ["data/alpha.csv"],
                "validation_threshold": {"min_rows": 1},
            }
        ],
    }
    (directory / "source_registry.yaml").write_text(
        yaml.safe_dump(payload, sort_keys=False),
        encoding="utf-8",
    )
    (directory / "source_registry.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return root


def _claim() -> dict:
    return {
        "schema_version": "moneysweep.source_equivalence/v1",
        "source_id": "alpha",
        "candidate_source": {
            "name": "Authoritative replacement",
            "source_url": "https://example.invalid/alpha",
            "authoritative": True,
        },
        "tests": {
            "semantic_scope_match": True,
            "temporal_scope_match": True,
            "row_universe_match": True,
            "field_mapping_complete": True,
            "selection_equivalent": True,
            "aggregation_equivalent": True,
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


def _materialize_evidence(root: Path, claim: dict) -> None:
    path = root / claim["evidence"][0]["locator"]
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = b'{"source_id":"alpha","comparison":"bounded"}\n'
    path.write_bytes(payload)
    claim["evidence"][0]["sha256"] = hashlib.sha256(payload).hexdigest()


def test_all_equivalence_dimensions_are_required(tmp_path: Path) -> None:
    root = _root(tmp_path)
    claim = _claim()
    _materialize_evidence(root, claim)
    claim["tests"]["row_universe_match"] = False

    report = verify(root=root, claim=claim)

    assert report["certified_equivalent"] is False
    assert report["decision"] == "PARTIAL_EQUIVALENCE"
    assert "row_universe_match" in report["blockers"]


def test_missing_fields_prevent_certified_equivalence(tmp_path: Path) -> None:
    root = _root(tmp_path)
    claim = _claim()
    _materialize_evidence(root, claim)
    claim["missing_fields"] = ["award_amount"]

    report = verify(root=root, claim=claim)

    assert report["certified_equivalent"] is False
    assert "missing_fields_present" in report["blockers"]


def test_authoritative_candidate_is_required(tmp_path: Path) -> None:
    root = _root(tmp_path)
    claim = _claim()
    _materialize_evidence(root, claim)
    claim["candidate_source"]["authoritative"] = False

    report = verify(root=root, claim=claim)

    assert report["certified_equivalent"] is False
    assert "candidate_not_authoritative" in report["blockers"]


def test_complete_claim_can_be_certified_equivalent(tmp_path: Path) -> None:
    root = _root(tmp_path)
    claim = _claim()
    _materialize_evidence(root, claim)

    report = verify(root=root, claim=claim)

    assert report["certified_equivalent"] is True
    assert report["decision"] == "CERTIFIED_EQUIVALENT"
    assert report["blockers"] == []
    assert report["verified_evidence_count"] == 1
    assert report["evidence"][0]["verified"] is True
    assert report["policy"]["silent_substitution_allowed"] is False
    assert report["policy"]["byte_verified_evidence_required"] is True


def test_missing_evidence_file_fails_closed(tmp_path: Path) -> None:
    root = _root(tmp_path)
    claim = _claim()

    report = verify(root=root, claim=claim)

    assert report["certified_equivalent"] is False
    assert "evidence_not_byte_verified" in report["blockers"]
    assert "evidence_file_missing" in report["evidence_blockers"]


def test_tampered_evidence_fails_closed(tmp_path: Path) -> None:
    root = _root(tmp_path)
    claim = _claim()
    _materialize_evidence(root, claim)
    path = root / claim["evidence"][0]["locator"]
    path.write_text("tampered\n", encoding="utf-8")

    report = verify(root=root, claim=claim)

    assert report["certified_equivalent"] is False
    assert "evidence_not_byte_verified" in report["blockers"]
    assert "evidence_sha256_mismatch" in report["evidence_blockers"]


def test_remote_only_evidence_cannot_certify(tmp_path: Path) -> None:
    root = _root(tmp_path)
    claim = _claim()
    claim["evidence"][0]["locator"] = "https://example.invalid/evidence.json"

    report = verify(root=root, claim=claim)

    assert report["certified_equivalent"] is False
    assert "evidence_not_byte_verified" in report["blockers"]
    assert "remote_evidence_not_byte_verified" in report["evidence_blockers"]
    assert report["policy"]["remote_only_evidence_can_certify"] is False
