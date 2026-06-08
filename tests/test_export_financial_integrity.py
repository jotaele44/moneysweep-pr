"""Financial-integrity, confidence, dedup, and synthetic-mode tests."""

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
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


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
def test_missing_confidence(tmp_path):
    pkg = _copy_fixture(tmp_path)
    _mutate(pkg, "funding_awards.jsonl", lambda rows: rows[0].pop("confidence"))
    assert "confidence_missing" in _codes(validate_package(pkg, mode="test"))


@pytest.mark.unit
def test_confidence_out_of_range(tmp_path):
    pkg = _copy_fixture(tmp_path)
    _mutate(pkg, "funding_awards.jsonl", lambda rows: rows[0].__setitem__("confidence", 1.5))
    assert "confidence_out_of_range" in _codes(validate_package(pkg, mode="test"))


@pytest.mark.unit
def test_negative_amount(tmp_path):
    pkg = _copy_fixture(tmp_path)
    _mutate(pkg, "funding_awards.jsonl", lambda rows: rows[0].__setitem__("amount", -5.0))
    assert "amount_negative" in _codes(validate_package(pkg, mode="test"))


@pytest.mark.unit
def test_non_numeric_amount(tmp_path):
    pkg = _copy_fixture(tmp_path)
    _mutate(pkg, "transactions.jsonl", lambda rows: rows[0].__setitem__("amount", "lots"))
    assert "amount_invalid" in _codes(validate_package(pkg, mode="test"))


@pytest.mark.unit
def test_missing_currency(tmp_path):
    pkg = _copy_fixture(tmp_path)
    _mutate(pkg, "funding_awards.jsonl", lambda rows: rows[0].pop("currency"))
    assert "currency_missing" in _codes(validate_package(pkg, mode="test"))


@pytest.mark.unit
def test_invalid_currency_code(tmp_path):
    pkg = _copy_fixture(tmp_path)
    _mutate(pkg, "funding_awards.jsonl", lambda rows: rows[0].__setitem__("currency", "us"))
    assert "currency_invalid" in _codes(validate_package(pkg, mode="test"))


@pytest.mark.unit
def test_duplicate_award_id(tmp_path):
    pkg = _copy_fixture(tmp_path)
    _mutate(pkg, "funding_awards.jsonl", lambda rows: rows.append(dict(rows[0])))
    assert "duplicate_id" in _codes(validate_package(pkg, mode="test"))


@pytest.mark.unit
def test_invalid_latitude(tmp_path):
    pkg = _copy_fixture(tmp_path)
    _mutate(
        pkg, "funding_awards.jsonl", lambda rows: rows[0]["location"].__setitem__("latitude", 999.0)
    )
    assert "location_invalid" in _codes(validate_package(pkg, mode="test"))


@pytest.mark.unit
def test_invalid_attribution_confidence(tmp_path):
    pkg = _copy_fixture(tmp_path)
    _mutate(
        pkg,
        "transactions.jsonl",
        lambda rows: rows[0]["location"].__setitem__("attribution_confidence", 2.0),
    )
    assert "location_invalid" in _codes(validate_package(pkg, mode="test"))


@pytest.mark.unit
def test_external_ids_must_be_object(tmp_path):
    pkg = _copy_fixture(tmp_path)
    _mutate(pkg, "entities.jsonl", lambda rows: rows[0].__setitem__("external_ids", "ACME123UEI"))
    assert "external_ids_invalid" in _codes(validate_package(pkg, mode="test"))


@pytest.mark.unit
def test_synthetic_rejected_in_production():
    assert "synthetic_in_production" in _codes(validate_package(FIXTURE, mode="production"))


@pytest.mark.unit
def test_synthetic_allowed_in_test():
    assert validate_package(FIXTURE, mode="test") == []
