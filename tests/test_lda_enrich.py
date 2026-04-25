"""Tests for scripts/lda_enrich.py — entity-level LDA enrichment helpers."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.lda_enrich import _normalize, _token_overlap


# ---------------------------------------------------------------------------
# _normalize
# ---------------------------------------------------------------------------

class TestNormalize:
    def test_empty_string(self):
        assert _normalize("") == ""

    def test_none(self):
        assert _normalize(None) == ""

    def test_uppercase(self):
        assert _normalize("crowley maritime") == "CROWLEY MARITIME"

    def test_strips_punctuation(self):
        # "Triple-S Management Corp" -> "TRIPLE S MANAGEMENT" (CORP is a suffix)
        assert _normalize("Triple-S Management Corp") == "TRIPLE S MANAGEMENT"

    def test_strips_trailing_suffix(self):
        assert _normalize("Microsoft Inc") == "MICROSOFT"

    def test_strips_multiple_suffixes(self):
        assert _normalize("Caribbean Data Services Inc Corp") == "CARIBBEAN DATA SERVICES"

    def test_collapses_whitespace(self):
        assert _normalize("Hospital   Damas   Inc") == "HOSPITAL DAMAS"

    def test_keeps_inner_words(self):
        # "INC" appearing in middle should NOT be stripped (only trailing)
        result = _normalize("INC Corp Solutions")
        # Only trailing suffixes pop; "INC" at front should stay
        assert "INC" in result.split()[0:1] or result.startswith("INC")


# ---------------------------------------------------------------------------
# _token_overlap
# ---------------------------------------------------------------------------

class TestTokenOverlap:
    def test_identical(self):
        assert _token_overlap("FOO BAR", "FOO BAR") == 1.0

    def test_disjoint(self):
        assert _token_overlap("FOO", "BAR") == 0.0

    def test_partial_overlap(self):
        # 2 of 3 tokens in `a` appear in `b` -> 2/3
        assert _token_overlap("FOO BAR BAZ", "FOO BAR") == pytest.approx(2 / 3)

    def test_a_subset_of_b(self):
        # All tokens in `a` appear in `b` -> 1.0
        assert _token_overlap("FOO BAR", "FOO BAR BAZ QUUX") == 1.0

    def test_empty_a(self):
        assert _token_overlap("", "FOO BAR") == 0.0

    def test_empty_b(self):
        assert _token_overlap("FOO", "") == 0.0

    def test_threshold_match_for_university_pr(self):
        # Real-world matching scenario:
        # entity:  "UNIVERSITY OF PUERTO RICO"
        # client:  "UNIVERSITY OF PUERTO RICO MEDICAL SCIENCES CAMPUS"
        # All 4 tokens of entity name appear in client -> 1.0
        assert _token_overlap(
            "UNIVERSITY OF PUERTO RICO",
            "UNIVERSITY OF PUERTO RICO MEDICAL SCIENCES CAMPUS",
        ) >= 0.80
