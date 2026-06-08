"""Tests for the canonical-master -> export-stream mapper."""

import json
from pathlib import Path

import pytest

from scripts.build_export_streams import build_streams
from scripts.build_export_package import build_package
from scripts.validate_export import validate_package

REPO_ROOT = Path(__file__).resolve().parent.parent
SAMPLE_INPUTS = REPO_ROOT / "tests" / "fixtures" / "sample_master_inputs"
GENERATED_AT = "2024-01-15T12:00:00Z"
STREAM_FILES = (
    "entities.jsonl",
    "sources.jsonl",
    "funding_awards.jsonl",
    "transactions.jsonl",
    "relationships.jsonl",
)


def _build(dest):
    staging = Path(dest) / "streams"
    report = build_streams(SAMPLE_INPUTS, staging, generated_at=GENERATED_AT)
    return staging, report


def _read_jsonl(path):
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


@pytest.mark.unit
def test_streams_validate_in_production_mode(tmp_path):
    staging, _ = _build(tmp_path)
    pkg = tmp_path / "pkg"
    build_package(input_dir=staging, output_dir=pkg, mode="production")
    assert validate_package(pkg, mode="production") == []


@pytest.mark.unit
def test_emitted_counts(tmp_path):
    _, report = _build(tmp_path)
    assert report["entities"]["emitted"] == 4  # 2 resolved + FEMA + DoD
    assert report["sources"]["emitted"] == 5
    assert report["funding_awards"]["emitted"] == 2
    assert report["transactions"]["emitted"] == 2
    assert report["relationships"]["emitted"] == 1


@pytest.mark.unit
def test_skip_accounting(tmp_path):
    _, report = _build(tmp_path)
    assert report["entities"]["skipped"].get("sentinel_or_aggregate") == 1
    awards_skipped = report["funding_awards"]["skipped"]
    assert awards_skipped.get("invalid_or_negative_amount") == 1
    assert awards_skipped.get("unresolved_recipient") == 1
    assert report["relationships"]["skipped"].get("unresolved_endpoint") == 1


@pytest.mark.unit
def test_no_negative_amounts(tmp_path):
    staging, _ = _build(tmp_path)
    for filename in ("funding_awards.jsonl", "transactions.jsonl"):
        for row in _read_jsonl(staging / filename):
            assert row["amount"] >= 0.0


@pytest.mark.unit
def test_all_rows_non_synthetic(tmp_path):
    staging, _ = _build(tmp_path)
    for filename in STREAM_FILES:
        for row in _read_jsonl(staging / filename):
            assert row["synthetic"] is False


@pytest.mark.unit
def test_dangling_recipient_not_emitted(tmp_path):
    staging, _ = _build(tmp_path)
    # The "GHOST CORP" award references an unresolved recipient and must be dropped.
    award_ids = [r["award_id"] for r in _read_jsonl(staging / "funding_awards.jsonl")]
    assert len(award_ids) == 2
    # No entity with normalized_name GHOST CORP should exist either.
    ent_norms = {r["normalized_name"] for r in _read_jsonl(staging / "entities.jsonl")}
    assert "GHOST CORP" not in ent_norms


@pytest.mark.unit
def test_deterministic_ids_across_runs(tmp_path):
    staging_a, _ = _build(tmp_path / "a")
    staging_b, _ = _build(tmp_path / "b")
    for filename in STREAM_FILES:
        assert (staging_a / filename).read_text(encoding="utf-8") == (
            staging_b / filename
        ).read_text(encoding="utf-8")


@pytest.mark.unit
def test_synthesized_funding_agency_present(tmp_path):
    staging, _ = _build(tmp_path)
    entities = _read_jsonl(staging / "entities.jsonl")
    agencies = {e["normalized_name"] for e in entities if e["entity_type"] == "funding_agency"}
    assert "FEDERAL EMERGENCY MANAGEMENT AGENCY" in agencies
    assert "DEPARTMENT OF DEFENSE" in agencies


@pytest.mark.unit
def test_resolved_entities_carry_external_ids(tmp_path):
    staging, _ = _build(tmp_path)
    by_norm = {e["normalized_name"]: e for e in _read_jsonl(staging / "entities.jsonl")}
    assert by_norm["ACME CONSTRUCTION"]["external_ids"]["uei"] == "ACME123UEI"
    assert by_norm["CARIBBEAN BUILDERS"]["external_ids"]["uei"] == "CARIB456UEI"
    # Synthesized agencies have no external ids.
    assert "external_ids" not in by_norm["DEPARTMENT OF DEFENSE"]


@pytest.mark.unit
def test_awards_carry_location(tmp_path):
    staging, _ = _build(tmp_path)
    awards = _read_jsonl(staging / "funding_awards.jsonl")
    locs = [a["location"] for a in awards if "location" in a]
    assert len(locs) == 2  # both emitted awards have a place of performance
    codes = {loc["municipality_code"] for loc in locs}
    assert codes == {"72127", "72113"}
    full = next(loc for loc in locs if loc["municipality_code"] == "72127")
    assert full["latitude"] == 18.4655 and full["longitude"] == -66.1057
    partial = next(loc for loc in locs if loc["municipality_code"] == "72113")
    assert "latitude" not in partial  # Ponce row had no lat/lon


@pytest.mark.unit
def test_transaction_location_optional(tmp_path):
    staging, _ = _build(tmp_path)
    txns = _read_jsonl(staging / "transactions.jsonl")
    with_loc = [t for t in txns if "location" in t]
    without_loc = [t for t in txns if "location" not in t]
    assert len(with_loc) == 1 and len(without_loc) == 1
    assert with_loc[0]["location"]["municipality_code"] == "72127"
