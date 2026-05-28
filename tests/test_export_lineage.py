"""Lineage, timestamp, and referential-integrity tests for the export validator."""
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


def _read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write_jsonl(path, rows):
    path.write_text(
        "".join(json.dumps(r, sort_keys=True, separators=(",", ":")) + "\n" for r in rows),
        encoding="utf-8",
    )


def _refresh_manifest(pkg):
    manifest = build_manifest(pkg, mode="test")
    (pkg / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _mutate(pkg, stream_file, fn):
    path = pkg / stream_file
    rows = _read_jsonl(path)
    fn(rows)
    _write_jsonl(path, rows)
    _refresh_manifest(pkg)


def _codes(errors):
    return {e.code for e in errors}


@pytest.mark.unit
def test_missing_lineage(tmp_path):
    pkg = _copy_fixture(tmp_path)
    _mutate(pkg, "entities.jsonl", lambda rows: rows[0].pop("lineage"))
    assert "lineage_missing" in _codes(validate_package(pkg, mode="test"))


@pytest.mark.unit
def test_lineage_not_object(tmp_path):
    pkg = _copy_fixture(tmp_path)
    _mutate(pkg, "entities.jsonl", lambda rows: rows[0].__setitem__("lineage", "nope"))
    assert "lineage_invalid" in _codes(validate_package(pkg, mode="test"))


@pytest.mark.unit
def test_bad_extracted_at(tmp_path):
    pkg = _copy_fixture(tmp_path)
    _mutate(pkg, "entities.jsonl", lambda rows: rows[0].__setitem__("extracted_at", "not-a-date"))
    assert "timestamp_invalid" in _codes(validate_package(pkg, mode="test"))


@pytest.mark.unit
def test_naive_timestamp_rejected(tmp_path):
    pkg = _copy_fixture(tmp_path)
    # No timezone offset -> not tz-aware -> rejected.
    _mutate(pkg, "entities.jsonl", lambda rows: rows[0].__setitem__("created_at", "2024-01-15T12:00:00"))
    assert "timestamp_invalid" in _codes(validate_package(pkg, mode="test"))


@pytest.mark.unit
def test_dangling_relationship_target(tmp_path):
    pkg = _copy_fixture(tmp_path)
    _mutate(pkg, "relationships.jsonl",
            lambda rows: rows[0].__setitem__("target_entity_id", "ent_" + "0" * 32))
    assert "dangling_entity_ref" in _codes(validate_package(pkg, mode="test"))


@pytest.mark.unit
def test_dangling_award_recipient(tmp_path):
    pkg = _copy_fixture(tmp_path)
    _mutate(pkg, "funding_awards.jsonl",
            lambda rows: rows[0].__setitem__("recipient_entity_id", "ent_" + "0" * 32))
    assert "dangling_entity_ref" in _codes(validate_package(pkg, mode="test"))


@pytest.mark.unit
def test_dangling_evidence_source(tmp_path):
    pkg = _copy_fixture(tmp_path)
    _mutate(pkg, "relationships.jsonl",
            lambda rows: rows[0].__setitem__("evidence_source_id", "src_" + "0" * 32))
    assert "dangling_entity_ref" in _codes(validate_package(pkg, mode="test"))


@pytest.mark.unit
def test_dangling_envelope_source(tmp_path):
    pkg = _copy_fixture(tmp_path)
    _mutate(pkg, "entities.jsonl",
            lambda rows: rows[0].__setitem__("source_id", "src_" + "0" * 32))
    assert "dangling_source_ref" in _codes(validate_package(pkg, mode="test"))
