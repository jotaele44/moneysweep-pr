from __future__ import annotations

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
                    }
                ],
            },
            sort_keys=False,
        ),
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
                "sha256": "a" * 64,
            }
        ],
    }


def test_all_equivalence_dimensions_are_required(tmp_path: Path) -> None:
    root = _root(tmp_path)
    claim = _claim()
    claim["tests"]["row_universe_match"] = False

    report = verify(root=root, claim=claim)

    assert report["certified_equivalent"] is False
    assert report["decision"] == "PARTIAL_EQUIVALENCE"
    assert "row_universe_match" in report["blockers"]


def test_missing_fields_prevent_certified_equivalence(tmp_path: Path) -> None:
    root = _root(tmp_path)
    claim = _claim()
    claim["missing_fields"] = ["award_amount"]

    report = verify(root=root, claim=claim)

    assert report["certified_equivalent"] is False
    assert "missing_fields_present" in report["blockers"]


def test_authoritative_candidate_is_required(tmp_path: Path) -> None:
    root = _root(tmp_path)
    claim = _claim()
    claim["candidate_source"]["authoritative"] = False

    report = verify(root=root, claim=claim)

    assert report["certified_equivalent"] is False
    assert "candidate_not_authoritative" in report["blockers"]


def test_complete_claim_can_be_certified_equivalent(tmp_path: Path) -> None:
    root = _root(tmp_path)

    report = verify(root=root, claim=_claim())

    assert report["certified_equivalent"] is True
    assert report["decision"] == "CERTIFIED_EQUIVALENT"
    assert report["blockers"] == []
    assert report["policy"]["silent_substitution_allowed"] is False
