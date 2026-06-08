"""Tests for scripts/write_source_manifests.py."""
import csv
import json

import pytest

from scripts.write_source_manifests import run


@pytest.fixture
def minimal_repo(tmp_path):
    """Repo with a 3-row staging CSV and a minimal source_registry."""
    # staging CSV
    staged = tmp_path / "data" / "staging" / "processed" / "pr_test_awards.csv"
    staged.parent.mkdir(parents=True)
    with staged.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["award_id", "recipient_name", "obligated_amount"])
        w.writeheader()
        w.writerow({"award_id": "A1", "recipient_name": "Acme Corp", "obligated_amount": "100"})
        w.writerow({"award_id": "A2", "recipient_name": "Beta LLC", "obligated_amount": "200"})
        w.writerow({"award_id": "A3", "recipient_name": "Gamma Inc", "obligated_amount": "300"})

    # minimal source_registry.json
    reg_dir = tmp_path / "registries"
    reg_dir.mkdir()
    registry = {
        "sources": [
            {
                "source_id": "test_source",
                "family": "federal",
                "required": True,
                "authentication": "none",
                "endpoint_url": "https://example.com",
                "producer_script": "scripts/fake_producer.py",
                "expected_outputs": ["data/staging/processed/pr_test_awards.csv"],
                "schema_version": "r5_v1",
            }
        ]
    }
    (reg_dir / "source_registry.json").write_text(json.dumps(registry), encoding="utf-8")
    # stub schema_registry.json
    (reg_dir / "schema_registry.json").write_text(
        json.dumps({"canonical_columns": {}, "tables": {}}), encoding="utf-8"
    )
    return tmp_path


@pytest.mark.unit
def test_run_writes_per_source_manifest(minimal_repo):
    results = run(minimal_repo, source_ids=["test_source"])
    assert "test_source" in results
    assert results["test_source"]["file_count"] == 1
    manifest_path = minimal_repo / results["test_source"]["manifest_path"]
    assert manifest_path.exists()
    payload = json.loads(manifest_path.read_text())
    assert payload["source_id"] == "test_source"
    assert payload["file_count"] == 1
    f = payload["files"][0]
    assert f["row_count"] == 3


@pytest.mark.unit
def test_run_dry_run_does_not_write(minimal_repo):
    results = run(minimal_repo, source_ids=["test_source"], dry_run=True)
    assert results["test_source"]["manifest_path"] == "(dry-run)"
    manifest_dir = minimal_repo / "data" / "manifests" / "test_source"
    assert not manifest_dir.exists()


@pytest.mark.unit
def test_run_missing_source_id_skips(minimal_repo):
    results = run(minimal_repo, source_ids=["nonexistent_source"])
    # No per-source entries; only _canonical summary key
    source_results = {k: v for k, v in results.items() if not k.startswith("_")}
    assert source_results == {}
