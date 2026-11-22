"""Tests for scripts/federation_export.py — the Hub-conformant canonical export."""

import json
import re

import pytest

from scripts import federation_export as fx

_TS = "2026-06-07T01:08:53.877935+00:00"


def _streams():
    lineage = {
        "producer_script": "moneysweep/federation/canonical_v1_bridge.py",
        "producer_phase": "CANONICAL_V1_FEDERATION_BRIDGE",
        "source_inputs": ["data/canonical_v1/evidence.csv"],
    }
    return {
        "sources": [
            {
                "source_id": "src_" + "a" * 32,
                "source_type": "registry",
                "source_name": "S",
                "source_ref": "r",
                "confidence": 0.9,
                "lineage": lineage,
                "synthetic": False,
                "created_at": _TS,
                "extracted_at": _TS,
            },
        ],
        "entities": [
            {
                "entity_id": "ent_" + "b" * 32,
                "source_id": "src_" + "a" * 32,
                "name": "Acme",
                "normalized_name": "ACME",
                "entity_type": "recipient",
                "jurisdiction": "PR",
                "confidence": 0.9,
                "lineage": lineage,
                "synthetic": False,
                "created_at": _TS,
                "extracted_at": _TS,
            },
        ],
        "relationships": [
            {
                "relationship_id": "rel_" + "c" * 32,
                "source_id": "src_" + "a" * 32,
                "source_entity_id": "ent_" + "b" * 32,
                "target_entity_id": "ent_" + "b" * 32,
                "relationship_type": "received_award_from",
                "evidence_source_id": "src_" + "a" * 32,
                "confidence": 0.9,
                "lineage": lineage,
                "synthetic": False,
                "created_at": _TS,
                "extracted_at": _TS,
            },
        ],
        "not_yet_federated": [],
    }


def test_write_package_manifest_is_hub_conformant(tmp_path):
    manifest = fx.write_package(_streams(), tmp_path, mode="test", now=_TS)

    # Required Hub federation_export_manifest fields.
    for key in (
        "package_id",
        "producer",
        "export_contract_version",
        "mode",
        "created_at",
        "federation",
        "files",
    ):
        assert key in manifest
    assert re.fullmatch(r"pkg_[a-f0-9]{32}", manifest["package_id"])
    assert manifest["producer"] == "moneysweep-pr"
    assert manifest["mode"] == "test"
    assert manifest["federation"] == {"producer_repo": "moneysweep-pr", "hub_parent": "thehub-pr"}

    streams = _streams()
    for f in manifest["files"]:
        assert f["stream"] in ("sources", "entities", "relationships")
        assert re.fullmatch(r"[a-f0-9]{64}", f["sha256"])
        assert f["record_count"] == len(streams[f["stream"]])
        assert (tmp_path / f["filename"]).exists()
    # manifest.json is written to disk and round-trips.
    assert json.loads((tmp_path / "manifest.json").read_text()) == manifest


def test_write_package_is_deterministic(tmp_path):
    a = fx.write_package(_streams(), tmp_path / "a", mode="test", now=_TS)
    b = fx.write_package(_streams(), tmp_path / "b", mode="test", now=_TS)
    assert a["package_id"] == b["package_id"]
    assert (tmp_path / "a" / "sources.jsonl").read_bytes() == (
        tmp_path / "b" / "sources.jsonl"
    ).read_bytes()


def test_mode_changes_package_id(tmp_path):
    test_id = fx.write_package(_streams(), tmp_path / "t", mode="test", now=_TS)["package_id"]
    prod_id = fx.write_package(_streams(), tmp_path / "p", mode="production", now=_TS)["package_id"]
    assert test_id != prod_id


def test_build_coverage_shape():
    cov = fx.build_coverage(_streams(), mode="test", now=_TS)
    assert cov["producer"] == "moneysweep-pr"
    assert cov["gate"] == "NON_PRODUCTION_DIAGNOSTIC"
    assert cov["stream_counts"] == {"sources": 1, "entities": 1, "relationships": 1}
    assert cov["edges_federated_pct"] == 100.0
    assert fx.build_coverage(_streams(), mode="production", now=_TS)["gate"] == "PRODUCTION"


def test_synthetic_counts_flags_synthetic_rows():
    streams = _streams()
    assert fx._synthetic_counts(streams) == {"sources": 0, "entities": 0, "relationships": 0}
    streams["entities"][0]["synthetic"] = True
    assert fx._synthetic_counts(streams)["entities"] == 1


def test_production_rejects_synthetic_but_test_allows(tmp_path, monkeypatch):
    syn = _streams()
    syn["entities"][0]["synthetic"] = True
    monkeypatch.setattr(fx, "build_streams", lambda root, now=None: syn)
    monkeypatch.setattr(fx, "merge_external_sources", lambda streams, root: 0)
    monkeypatch.setattr(fx, "validate_rows", lambda streams, root: [])

    # production must reject and write nothing
    assert fx.main(["--mode", "production", "--out", str(tmp_path / "p")]) == 1
    assert not (tmp_path / "p" / "manifest.json").exists()
    # the same rows are permitted in test mode
    assert fx.main(["--mode", "test", "--out", str(tmp_path / "t")]) == 0
    assert (tmp_path / "t" / "manifest.json").exists()


def test_bridge_rerun_refreshes_hub_manifest(tmp_path):
    """A legacy-bridge rerun must keep manifest.json in sync with the streams it
    rewrites (no stale sha256s)."""
    import hashlib

    from scripts import bridge_canonical_v1_federation as br

    br.write_streams(_streams(), tmp_path)
    pkg = tmp_path / "data" / "exports" / "canonical_v1_federation"
    manifest = json.loads((pkg / "manifest.json").read_text())
    assert re.fullmatch(r"pkg_[a-f0-9]{32}", manifest["package_id"])
    assert manifest["producer"] == "moneysweep-pr"
    assert (pkg / "coverage.json").exists()
    for f in manifest["files"]:
        assert f["sha256"] == hashlib.sha256((pkg / f["filename"]).read_bytes()).hexdigest()


@pytest.mark.integration
def test_main_end_to_end_writes_valid_package(tmp_path):
    # Runs the real bridge against repo data and writes a package to tmp_path.
    rc = fx.main(["--mode", "test", "--now", _TS, "--out", str(tmp_path)])
    assert rc == 0
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert manifest["producer"] == "moneysweep-pr"
    assert {f["stream"] for f in manifest["files"]} == {
        "sources",
        "entities",
        "relationships",
        "source_monitors",
    }
    assert (tmp_path / "coverage.json").exists()
    # Every declared file exists with a matching record count.
    for f in manifest["files"]:
        lines = [ln for ln in (tmp_path / f["filename"]).read_text().splitlines() if ln.strip()]
        assert len(lines) == f["record_count"]
