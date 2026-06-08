"""Tests for the canonical_v1 evidence pipeline (tiering + builder)."""

import csv

import pytest

from contract_sweeper.runtime import evidence_tiers as et
from contract_sweeper.validation import canonical_v1_schema as cv1
from scripts import build_evidence as be


@pytest.mark.unit
def test_derive_tier_caps_by_method():
    assert et.derive_tier("registry", "manual") == "T1"
    assert et.derive_tier("registry", "OCR") == "T3"  # method caps below source
    assert et.derive_tier("csv", "parser") == "T2"
    assert et.derive_tier("web", "web") == "T3"
    assert et.derive_tier("mystery", None) == "T4"


@pytest.mark.unit
def test_score_evidence_applies_ocr_confidence():
    assert et.score_evidence("T1") == 0.95
    assert et.score_evidence("T3", "OCR", ocr_confidence=0.5) == pytest.approx(0.3)


@pytest.mark.unit
def test_claim_tier_crosswalk():
    assert et.claim_tier_for("T1", "accepted") == "observed"
    assert et.claim_tier_for("T1", "pending") == "linked"  # downgraded
    assert et.claim_tier_for("T2", "rejected") == "blocked"
    assert et.claim_tier_for("T4", "accepted") == "inferred"


@pytest.mark.unit
def test_make_evidence_is_deterministic_and_derives_fields():
    a = be.make_evidence(
        source_type="registry",
        source_name="PR Lobby Registry",
        claim="LGA represents Genera PR",
        page_or_line_ref="row 5",
        extraction_method="manual",
        review_status="accepted",
    )
    b = be.make_evidence(
        source_type="registry",
        source_name="PR Lobby Registry",
        claim="LGA represents Genera PR",
        page_or_line_ref="row 5",
        extraction_method="manual",
        review_status="accepted",
    )
    assert a.evidence_id == b.evidence_id
    assert a.evidence_tier == "T1"
    assert a.confidence == 0.95
    assert a.claim_tier() == "observed"
    # new evidence defaults to pending, which downgrades the claim tier
    pend = be.make_evidence(source_type="registry", source_name="S", claim="c")
    assert pend.review_status == "pending"
    assert pend.claim_tier() == "linked"


@pytest.mark.unit
def test_dedupe_keeps_highest_confidence():
    low = be.make_evidence(source_type="web", source_name="S", claim="c", page_or_line_ref="r")
    high = be.make_evidence(source_type="web", source_name="S", claim="c", page_or_line_ref="r")
    high.confidence = 0.99
    deduped = be.dedupe_evidence([low, high])
    assert len(deduped) == 1
    assert deduped[0].confidence == 0.99


@pytest.mark.integration
def test_from_csv_source_emits_one_row_per_data_row(tmp_path):
    src = tmp_path / "src.csv"
    with src.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["a", "b"])
        w.writerow(["1", "2"])
        w.writerow(["3", "4"])
    items = be.from_csv_source(src, source_name="src.csv")
    assert len(items) == 2
    assert items[0].page_or_line_ref == "row 2"


@pytest.mark.integration
def test_write_evidence_roundtrips_and_validates(tmp_path):
    items = be.dedupe_evidence(
        [
            be.make_evidence(
                source_type="registry",
                source_name="S1",
                claim="claim one",
                page_or_line_ref="row 2",
                extraction_method="manual",
                review_status="accepted",
            ),
            be.make_evidence(
                source_type="csv", source_name="S2", claim="claim two", page_or_line_ref="row 3"
            ),
        ]
    )
    out = tmp_path / "evidence.csv"
    manifest = be.write_evidence(items, out)
    assert manifest["row_count"] == 2
    assert manifest["tier_counts"]["T1"] == 1

    # every written row validates against the evidence schema
    schema = cv1.load_schema("evidence", cv1.REPO_ROOT)
    with out.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            assert cv1.validate_row(row, schema) == [], row
