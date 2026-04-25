"""Tests for scripts/sam_enrichment.py — name normalization and target loading."""

import csv
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.sam_enrichment import (
    load_targets,
    name_similarity,
    normalize_vendor,
    vendor_hash,
)


# ---------------------------------------------------------------------------
# normalize_vendor
# ---------------------------------------------------------------------------

class TestNormalizeVendor:
    def test_uppercase(self):
        assert normalize_vendor("acme corp") == "ACME"

    def test_strips_legal_suffixes(self):
        assert normalize_vendor("Microsoft Inc.") == "MICROSOFT"
        assert normalize_vendor("ACME LLC") == "ACME"
        assert normalize_vendor("Foo Corporation") == "FOO"

    def test_strips_punctuation(self):
        assert normalize_vendor("Triple-S, Inc.") == "TRIPLE S"

    def test_collapses_whitespace(self):
        assert normalize_vendor("  Foo   Bar  ") == "FOO BAR"


# ---------------------------------------------------------------------------
# name_similarity
# ---------------------------------------------------------------------------

class TestNameSimilarity:
    def test_identical(self):
        assert name_similarity("FOO BAR", "FOO BAR") == 1.0

    def test_disjoint(self):
        assert name_similarity("FOO", "BAR") == 0.0

    def test_jaccard_partial(self):
        # tokens A={FOO,BAR}, B={FOO,BAZ} -> intersect=1, union=3 -> 1/3
        assert name_similarity("FOO BAR", "FOO BAZ") == pytest.approx(1 / 3)

    def test_empty_returns_zero(self):
        assert name_similarity("", "FOO") == 0.0
        assert name_similarity("FOO", "") == 0.0


# ---------------------------------------------------------------------------
# vendor_hash
# ---------------------------------------------------------------------------

class TestVendorHash:
    def test_stable_for_same_input(self):
        assert vendor_hash("Foo Inc.") == vendor_hash("Foo Inc.")

    def test_normalized_equivalence(self):
        # "Foo Inc" and "FOO INC" should hash the same after normalization
        assert vendor_hash("Foo Inc") == vendor_hash("FOO INC")

    def test_returns_12_chars(self):
        assert len(vendor_hash("anything")) == 12


# ---------------------------------------------------------------------------
# load_targets — unified master fallback
# ---------------------------------------------------------------------------

class TestLoadTargetsFallback:
    def _make_dirs(self, root: Path) -> Path:
        d = root / "data" / "staging" / "processed"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def test_raises_when_no_master_exists(self, tmp_path):
        self._make_dirs(tmp_path)
        with pytest.raises(FileNotFoundError):
            load_targets(tmp_path)

    def test_falls_back_to_unified_master(self, tmp_path):
        """When pr_contracts_master.csv is absent, reads pr_all_awards_master.csv
        and uses recipient_name as the vendor_name role."""
        d = self._make_dirs(tmp_path)
        unified = d / "pr_all_awards_master.csv"
        with open(unified, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["recipient_name", "obligated_amount"])
            w.writeheader()
            w.writerow({"recipient_name": "Crowley Maritime Corp", "obligated_amount": "1000000"})
            w.writerow({"recipient_name": "Crowley Maritime Corp", "obligated_amount": "500000"})
            w.writerow({"recipient_name": "Microsoft Inc", "obligated_amount": "250000"})
            w.writerow({"recipient_name": "", "obligated_amount": "999"})  # skipped

        targets = load_targets(tmp_path)
        assert len(targets) == 2
        # Should aggregate Crowley to 1.5M
        crowley = next(t for t in targets if t["vendor_name"] == "Crowley Maritime Corp")
        assert crowley["total_value"] == 1_500_000
        assert crowley["record_count"] == 2

    def test_prefers_legacy_master_when_present(self, tmp_path):
        """When both files exist, pr_contracts_master.csv takes precedence."""
        d = self._make_dirs(tmp_path)
        legacy = d / "pr_contracts_master.csv"
        with open(legacy, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["vendor_name", "obligated_amount"])
            w.writeheader()
            w.writerow({"vendor_name": "Legacy Vendor", "obligated_amount": "500"})
        unified = d / "pr_all_awards_master.csv"
        with open(unified, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["recipient_name", "obligated_amount"])
            w.writeheader()
            w.writerow({"recipient_name": "Unified Vendor", "obligated_amount": "999"})

        targets = load_targets(tmp_path)
        names = {t["vendor_name"] for t in targets}
        assert "Legacy Vendor" in names
        assert "Unified Vendor" not in names
