"""Fail-closed validation tests for the Contract-Sweeper producer package."""
from __future__ import annotations

import json

from contract_sweeper.federation.export_writer import write_package
from contract_sweeper.federation.namespace import namespaced_id
from contract_sweeper.federation.validator import (
    validate_envelope,
    validate_financial,
    validate_package,
)
from tests._federation_fixtures import build_streams


def _streams_as_dicts(synthetic=True):
    return {
        name: [r.to_dict() for r in records]
        for name, records in build_streams(synthetic=synthetic).items()
    }


def test_synthetic_package_passes():
    result = validate_package(_streams_as_dicts())
    assert result["valid"], result["errors"]
    assert result["count"] == 6


def test_empty_package_fails_closed():
    assert validate_package({})["valid"] is False
    assert validate_package([])["valid"] is False


def test_unnamespaced_id_fails():
    streams = _streams_as_dicts()
    streams["entities"][0]["record_id"] = "ent_acme"  # missing prefix
    result = validate_package(streams)
    assert not result["valid"]
    assert any("namespaced" in e for e in result["errors"])


def test_financial_requires_amount_and_currency():
    bad = {
        "record_type": "funding_award",
        "payload": {"currency": "usd"},  # bad case currency, missing amount
        "lineage": [],
    }
    errors = validate_financial(bad)
    assert any("amount" in e for e in errors)
    assert any("currency" in e for e in errors)
    assert any("lineage" in e for e in errors)


def test_negative_amount_fails():
    streams = _streams_as_dicts()
    streams["funding_awards"][0]["payload"]["amount"] = -5
    assert not validate_package(streams)["valid"]


def test_confidence_out_of_range_fails():
    rec = build_streams()["entities"][0].to_dict()
    rec["confidence"] = {"score": 1.5, "method": "x"}
    assert any("confidence.score" in e for e in validate_envelope(rec))


def test_relationship_referential_integrity():
    streams = _streams_as_dicts()
    # Point the relationship at an entity that does not exist in the package.
    streams["relationships"][0]["entities"][0]["entity_id"] = namespaced_id("ent_ghost")
    result = validate_package(streams)
    assert not result["valid"]
    assert any("unknown entity_id" in e for e in result["errors"])


def test_production_mode_rejects_synthetic():
    streams = _streams_as_dicts(synthetic=True)
    assert validate_package(streams, reject_synthetic=True)["valid"] is False
    # The same data is fine when synthetic rows are allowed (test mode).
    assert validate_package(streams, reject_synthetic=False)["valid"] is True


def test_written_package_reloads_and_validates(tmp_path):
    manifest = write_package(tmp_path, build_streams(), synthetic=True)
    assert manifest["producer"] == "contract-sweeper"
    assert {f["filename"] for f in manifest["files"]} == {
        "funding_awards.jsonl",
        "transactions.jsonl",
        "entities.jsonl",
        "relationships.jsonl",
        "sources.jsonl",
    }
    reloaded = {}
    for spec in manifest["files"]:
        stem = spec["filename"].replace(".jsonl", "")
        lines = (tmp_path / spec["filename"]).read_text(encoding="utf-8").splitlines()
        reloaded[stem] = [json.loads(line) for line in lines if line.strip()]
    assert validate_package(reloaded)["valid"]
