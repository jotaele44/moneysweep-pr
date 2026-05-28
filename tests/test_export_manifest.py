"""Manifest-integrity and federation-handshake tests for the export validator."""
import json
import shutil
from pathlib import Path

import pytest

from scripts.build_export_package import build_manifest
from scripts.validate_export import validate_package

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "valid_funding_entity_export"


def _copy_fixture(tmp_path):
    dst = tmp_path / "pkg"
    shutil.copytree(FIXTURE, dst)
    return dst


def _load_manifest(pkg):
    return json.loads((pkg / "manifest.json").read_text(encoding="utf-8"))


def _write_manifest(pkg, manifest):
    (pkg / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _codes(errors):
    return {e.code for e in errors}


@pytest.mark.unit
def test_fixture_valid_in_test_mode():
    assert validate_package(FIXTURE, mode="test") == []


@pytest.mark.unit
def test_missing_manifest(tmp_path):
    pkg = _copy_fixture(tmp_path)
    (pkg / "manifest.json").unlink()
    assert "manifest_missing" in _codes(validate_package(pkg, mode="test"))


@pytest.mark.unit
def test_unparseable_manifest(tmp_path):
    pkg = _copy_fixture(tmp_path)
    (pkg / "manifest.json").write_text("{not json", encoding="utf-8")
    assert "manifest_unparseable" in _codes(validate_package(pkg, mode="test"))


@pytest.mark.unit
def test_dropped_file_entry(tmp_path):
    pkg = _copy_fixture(tmp_path)
    manifest = _load_manifest(pkg)
    manifest["files"] = manifest["files"][:-1]
    _write_manifest(pkg, manifest)
    assert "manifest_files_missing" in _codes(validate_package(pkg, mode="test"))


@pytest.mark.unit
def test_missing_stream_file_on_disk(tmp_path):
    pkg = _copy_fixture(tmp_path)
    (pkg / "transactions.jsonl").unlink()
    assert "manifest_files_missing" in _codes(validate_package(pkg, mode="test"))


@pytest.mark.unit
def test_tampered_sha256(tmp_path):
    pkg = _copy_fixture(tmp_path)
    manifest = _load_manifest(pkg)
    manifest["files"][0]["sha256"] = "0" * 64
    _write_manifest(pkg, manifest)
    assert "manifest_sha256_mismatch" in _codes(validate_package(pkg, mode="test"))


@pytest.mark.unit
def test_wrong_record_count(tmp_path):
    pkg = _copy_fixture(tmp_path)
    manifest = _load_manifest(pkg)
    manifest["files"][0]["record_count"] += 99
    _write_manifest(pkg, manifest)
    assert "manifest_row_count_mismatch" in _codes(validate_package(pkg, mode="test"))


@pytest.mark.unit
def test_missing_federation_block(tmp_path):
    pkg = _copy_fixture(tmp_path)
    manifest = _load_manifest(pkg)
    del manifest["federation"]
    _write_manifest(pkg, manifest)
    assert "federation_invalid" in _codes(validate_package(pkg, mode="test"))


@pytest.mark.unit
def test_wrong_consumer_repo(tmp_path):
    pkg = _copy_fixture(tmp_path)
    manifest = _load_manifest(pkg)
    manifest["federation"]["consumer_repo"] = "some-other-repo"
    _write_manifest(pkg, manifest)
    assert "federation_invalid" in _codes(validate_package(pkg, mode="test"))


@pytest.mark.unit
def test_build_manifest_emits_spiderweb_handshake():
    manifest = build_manifest(FIXTURE, mode="test")
    fed = manifest["federation"]
    assert fed["consumer_repo"] == "spiderweb-pr"
    assert fed["consumer_component"] == "query-hub"
    assert fed["contract"] == "contract-sweeper-export"
    assert fed["producer_repo"] == "contract-sweeper"
