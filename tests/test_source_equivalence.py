from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
import yaml

from tools.verify_source_equivalence import verify

pytestmark = pytest.mark.unit


def _root(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    path = root / "registries/source_registry.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(
        yaml.safe_dump(
            {
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
                    },
                    {
                        "source_id": "beta",
                        "family": "test",
                        "required": False,
                        "authentication": "none",
                        "producer_script": "scripts/beta.py",
                        "expected_outputs": ["data/beta.csv"],
                        "validation_threshold": {"min_rows": 1},
                    },
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    data = root / "data"
    data.mkdir()
    (data / "alpha.csv").write_text(
        "record_id,value\nA,10\nB,20\n",
        encoding="utf-8",
    )
    (data / "beta.csv").write_text(
        "record_id,value\nA,10\nB,20\n",
        encoding="utf-8",
    )
    return root


def _evidence(root: Path, locator: str) -> dict:
    path = root / locator
    return {
        "kind": "source_snapshot",
        "locator": locator,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def _claim(root: Path) -> dict:
    return {
        "schema_version": "moneysweep.source_equivalence/v2",
        "source_id": "alpha",
        "candidate_source": {
            "source_id": "beta",
            "name": "Registered authoritative replacement",
            "source_url": "https://example.invalid/beta",
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
            _evidence(root, "data/alpha.csv"),
            _evidence(root, "data/beta.csv"),
        ],
        "row_set_comparison": {
            "a_locator": "data/alpha.csv",
            "b_locator": "data/beta.csv",
            "key_fields": ["record_id"],
            "identity_basis": "stable_id",
        },
    }


def test_all_equivalence_dimensions_are_required(tmp_path: Path) -> None:
    root = _root(tmp_path)
    claim = _claim(root)
    claim["tests"]["row_universe_match"] = False

    report = verify(root=root, claim=claim)

    assert report["certified_equivalent"] is False
    assert report["decision"] == "PARTIAL_EQUIVALENCE"
    assert "row_universe_match" in report["blockers"]


def test_missing_fields_prevent_certified_equivalence(tmp_path: Path) -> None:
    root = _root(tmp_path)
    claim = _claim(root)
    claim["missing_fields"] = ["award_amount"]

    report = verify(root=root, claim=claim)

    assert report["certified_equivalent"] is False
    assert "missing_fields_present" in report["blockers"]


def test_authoritative_candidate_is_required(tmp_path: Path) -> None:
    root = _root(tmp_path)
    claim = _claim(root)
    claim["candidate_source"]["authoritative"] = False

    report = verify(root=root, claim=claim)

    assert report["certified_equivalent"] is False
    assert "candidate_not_authoritative" in report["blockers"]


def test_registered_candidate_source_is_required(tmp_path: Path) -> None:
    root = _root(tmp_path)
    claim = _claim(root)
    claim["candidate_source"]["source_id"] = "ghost"

    report = verify(root=root, claim=claim)

    assert report["certified_equivalent"] is False
    assert "candidate_source_id_not_registered" in report["errors"]


def test_tampered_evidence_prevents_certified_equivalence(tmp_path: Path) -> None:
    root = _root(tmp_path)
    claim = _claim(root)
    (root / "data/alpha.csv").write_text(
        "record_id,value\nA,999\nB,20\n",
        encoding="utf-8",
    )

    report = verify(root=root, claim=claim)

    assert report["certified_equivalent"] is False
    assert "evidence_not_byte_verified" in report["blockers"]
    assert "evidence_0_sha256_mismatch" in report["errors"]
    assert "a_comparison_bytes_not_verified" in report["blockers"]


def test_complete_claim_can_be_certified_equivalent(tmp_path: Path) -> None:
    root = _root(tmp_path)

    report = verify(root=root, claim=_claim(root))

    assert report["certified_equivalent"] is True
    assert report["decision"] == "CERTIFIED_EQUIVALENT"
    assert report["blockers"] == []
    algebra = report["row_set_comparison"]
    assert algebra["intersection"] == 2
    assert algebra["a_only"] == 0
    assert algebra["b_only"] == 0
    assert algebra["union"] == 2
    assert algebra["symmetric_difference"] == 0
    assert report["policy"]["computed_set_algebra_required"] is True
    assert report["policy"]["name_only_identity_allowed"] is False


def test_a_only_and_b_only_are_computed_and_block_certification(tmp_path: Path) -> None:
    root = _root(tmp_path)
    (root / "data/alpha.csv").write_text(
        "record_id,value\nA,10\nB,20\n",
        encoding="utf-8",
    )
    (root / "data/beta.csv").write_text(
        "record_id,value\nA,10\nC,30\n",
        encoding="utf-8",
    )
    claim = _claim(root)

    report = verify(root=root, claim=claim)

    assert report["certified_equivalent"] is False
    algebra = report["row_set_comparison"]
    assert algebra["intersection"] == 1
    assert algebra["a_only"] == 1
    assert algebra["b_only"] == 1
    assert algebra["union"] == 3
    assert algebra["symmetric_difference"] == 2
    assert algebra["a_only_keys"] == [["B"]]
    assert algebra["b_only_keys"] == [["C"]]
    assert "computed_row_universe_mismatch" in report["blockers"]


def test_name_only_identity_is_disallowed(tmp_path: Path) -> None:
    root = _root(tmp_path)
    (root / "data/alpha.csv").write_text("name,value\nSame,10\n", encoding="utf-8")
    (root / "data/beta.csv").write_text("name,value\nSame,10\n", encoding="utf-8")
    claim = _claim(root)
    claim["evidence"] = [
        _evidence(root, "data/alpha.csv"),
        _evidence(root, "data/beta.csv"),
    ]
    claim["row_set_comparison"]["key_fields"] = ["name"]

    report = verify(root=root, claim=claim)

    assert report["certified_equivalent"] is False
    assert "name_only_identity_disallowed" in report["blockers"]


def test_duplicate_and_null_identity_keys_fail_closed(tmp_path: Path) -> None:
    root = _root(tmp_path)
    (root / "data/alpha.csv").write_text(
        "record_id,value\nA,10\nA,11\n,12\n",
        encoding="utf-8",
    )
    (root / "data/beta.csv").write_text(
        "record_id,value\nA,10\n,12\n",
        encoding="utf-8",
    )
    claim = _claim(root)

    report = verify(root=root, claim=claim)

    assert report["certified_equivalent"] is False
    algebra = report["row_set_comparison"]
    assert algebra["a_duplicate_key_rows"] == 1
    assert algebra["a_null_key_rows"] == 1
    assert algebra["b_null_key_rows"] == 1
    assert "a_duplicate_identity_keys" in report["blockers"]
    assert "a_null_identity_keys" in report["blockers"]
    assert "b_null_identity_keys" in report["blockers"]


def test_missing_key_field_fails_closed(tmp_path: Path) -> None:
    root = _root(tmp_path)
    claim = _claim(root)
    claim["row_set_comparison"]["key_fields"] = ["stable_missing_id"]

    report = verify(root=root, claim=claim)

    assert report["certified_equivalent"] is False
    assert "a_missing_key_fields:stable_missing_id" in report["blockers"]
    assert "b_missing_key_fields:stable_missing_id" in report["blockers"]
