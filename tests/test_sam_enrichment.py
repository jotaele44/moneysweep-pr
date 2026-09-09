"""Tests for scripts/sam_enrichment.py — name normalization and target loading."""

import csv
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import scripts.sam_enrichment as se
from moneysweep.runtime.name_normalization import normalize_name
from scripts.sam_enrichment import (
    STATUS_DEFERRED_API,
    STATUS_LOOKUP_ERROR,
    STATUS_NO_FEDERAL_MATCH,
    STATUS_RESOLVED_LOCAL_GOV,
    STATUS_RESOLVED_SOURCE_UEI,
    cluster_key,
    load_municipio_index,
    load_targets,
    local_resolve,
    name_similarity,
    normalize_vendor,
    sam_lookup_by_name,
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

    def test_folds_accents(self):
        # NFKD accent-folding so Spanish source names line up with SAM's ASCII.
        assert normalize_vendor("Autónomo") == "AUTONOMO"
        assert normalize_vendor("MUNICIPIO DE BAYAMÓN") == "MUNICIPIO DE BAYAMON"
        # accented and unaccented spellings must normalize identically
        assert normalize_vendor("Compañía Ñandú") == normalize_vendor("Compania Nandu")


# ---------------------------------------------------------------------------
# cluster_key — alias-cluster deduplication
# ---------------------------------------------------------------------------


class TestClusterKey:
    def test_collapses_alias_variants(self):
        canon = normalize_name("FOO CANON")
        overrides = {
            normalize_name("Foo One Inc"): canon,
            normalize_name("Foo Two LLC"): canon,
        }
        # Both curated aliases hash to the same cache key → one lookup serves both.
        assert cluster_key("Foo One Inc", overrides) == cluster_key("Foo Two LLC", overrides)

    def test_distinct_for_unrelated_names(self):
        assert cluster_key("Alpha Corp", {}) != cluster_key("Beta Corp", {})

    def test_returns_12_chars(self):
        assert len(cluster_key("Anything Inc", {})) == 12


# ---------------------------------------------------------------------------
# local_resolve / load_municipio_index — offline PR-government classification
# ---------------------------------------------------------------------------


class TestLocalResolve:
    def _make_municipio_csv(self, root):
        d = root / "data" / "reference"
        d.mkdir(parents=True, exist_ok=True)
        with open(d / "pr_78_municipio_crosswalk.csv", "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["municipality_name", "aliases"])
            w.writeheader()
            w.writerow(
                {"municipality_name": "Adjuntas", "aliases": "Adjuntas|MUNICIPIO DE ADJUNTAS"}
            )
            w.writerow({"municipality_name": "Bayamón", "aliases": "Bayamón|MUNICIPIO DE BAYAMÓN"})
        return root

    def test_classifies_municipal_government(self, tmp_path):
        idx = load_municipio_index(self._make_municipio_csv(tmp_path))
        res = local_resolve("Municipio de Adjuntas", idx)
        assert res is not None
        assert res["resolution_status"] == STATUS_RESOLVED_LOCAL_GOV
        assert res["uei"] == ""  # PR gov entities carry no SAM UEI by design

    def test_accent_insensitive_municipio_match(self, tmp_path):
        idx = load_municipio_index(self._make_municipio_csv(tmp_path))
        # unaccented input still matches the accented crosswalk entry
        assert local_resolve("Municipio de Bayamon", idx) is not None

    def test_matches_english_and_autonomo_forms(self, tmp_path):
        idx = load_municipio_index(self._make_municipio_csv(tmp_path))
        # English "MUNICIPALITY OF X" and Spanish "MUNICIPIO AUTÓNOMO DE X" forms
        # also classify as PR government (not just "MUNICIPIO DE X").
        assert local_resolve("Municipality of Adjuntas", idx) is not None
        assert local_resolve("Municipio Autónomo de Bayamón", idx) is not None
        assert local_resolve("Autonomous Municipality of Adjuntas", idx) is not None

    def test_does_not_misclassify_contractor_sharing_town_name(self, tmp_path):
        idx = load_municipio_index(self._make_municipio_csv(tmp_path))
        # only "MUNICIPIO DE X" forms are indexed, never the bare town name
        assert local_resolve("Adjuntas Trucking Corp", idx) is None
        assert local_resolve("Microsoft Inc", idx) is None


# ---------------------------------------------------------------------------
# sam_lookup_by_name — transient-error vs definitive-no-match signal
# ---------------------------------------------------------------------------


class TestLookupErrorSignal:
    def test_transport_failure_is_errored(self, monkeypatch):
        monkeypatch.setattr(se, "sam_call", lambda *a, **k: None)  # every call fails
        monkeypatch.setattr(se.time, "sleep", lambda *a, **k: None)  # no retry backoff wait
        match, errored = sam_lookup_by_name("Whatever Inc", "KEY")
        assert match is None
        assert errored is True

    def test_empty_result_is_not_errored(self, monkeypatch):
        monkeypatch.setattr(se, "sam_call", lambda *a, **k: {"entityData": []})
        match, errored = sam_lookup_by_name("Whatever Inc", "KEY")
        assert match is None
        assert errored is False  # a real "no match" answer, not a transient error


# reason-code constants are importable and distinct (guards accidental collisions)
def test_reason_codes_distinct():
    codes = {STATUS_LOOKUP_ERROR, STATUS_NO_FEDERAL_MATCH, STATUS_RESOLVED_LOCAL_GOV}
    assert len(codes) == 3


# ---------------------------------------------------------------------------
# name_similarity
# ---------------------------------------------------------------------------


class TestNameSimilarity:
    def test_identical(self):
        assert name_similarity("FOO BAR", "FOO BAR") == 1.0

    def test_disjoint(self):
        assert name_similarity("FOO", "BAR") == 0.0

    def test_partial_overlap_above_jaccard_floor(self):
        # Hybrid returns max(jaccard, rapidfuzz); must be >= pure Jaccard (1/3)
        score = name_similarity("FOO BAR", "FOO BAZ")
        assert score >= 1 / 3
        assert score <= 1.0

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

    def test_preserves_value_weighted_source_uei(self, tmp_path):
        d = self._make_dirs(tmp_path)
        master = d / "pr_contracts_master.csv"
        with open(master, "w", newline="") as f:
            w = csv.DictWriter(
                f,
                fieldnames=["vendor_name", "obligated_amount", "recipient_uei"],
            )
            w.writeheader()
            w.writerow(
                {
                    "vendor_name": "Acme Inc",
                    "obligated_amount": "100",
                    "recipient_uei": "OLDUEI000001",
                }
            )
            w.writerow(
                {
                    "vendor_name": "Acme Inc",
                    "obligated_amount": "900",
                    "recipient_uei": "BESTUEI00001",
                }
            )
        targets = load_targets(tmp_path)
        assert targets[0]["source_uei"] == "BESTUEI00001"

    def test_rebuilds_target_cache_when_master_is_newer(self, tmp_path):
        d = self._make_dirs(tmp_path)
        master = d / "pr_contracts_master.csv"

        def write_master(vendor):
            with open(master, "w", newline="") as f:
                w = csv.DictWriter(
                    f,
                    fieldnames=["vendor_name", "obligated_amount", "recipient_uei"],
                )
                w.writeheader()
                w.writerow({"vendor_name": vendor, "obligated_amount": "1", "recipient_uei": ""})

        write_master("Old Vendor")
        assert load_targets(tmp_path)[0]["vendor_name"] == "Old Vendor"
        target_cache = d / "vendor_targets.csv"
        write_master("New Vendor")
        newer = target_cache.stat().st_mtime_ns + 1_000_000_000
        os.utime(master, ns=(newer, newer))
        assert load_targets(tmp_path)[0]["vendor_name"] == "New Vendor"


class TestOfflineFirstRun:
    @staticmethod
    def _master(root: Path, rows: list[dict]) -> None:
        d = root / "data" / "staging" / "processed"
        d.mkdir(parents=True, exist_ok=True)
        with open(d / "pr_contracts_master.csv", "w", newline="") as f:
            w = csv.DictWriter(
                f,
                fieldnames=["vendor_name", "obligated_amount", "recipient_uei"],
            )
            w.writeheader()
            w.writerows(rows)

    def test_default_run_needs_no_api_key_and_uses_source_uei(self, tmp_path, monkeypatch):
        self._master(
            tmp_path,
            [
                {
                    "vendor_name": "Acme Inc",
                    "obligated_amount": "500",
                    "recipient_uei": "ACMEUEI00001",
                },
                {
                    "vendor_name": "Residual LLC",
                    "obligated_amount": "10",
                    "recipient_uei": "",
                },
            ],
        )
        monkeypatch.setattr(se, "get_sam_api_key", lambda: pytest.fail("key should not load"))
        summary = se.run(root=tmp_path)
        assert summary["vendors_resolved"] == 1
        assert summary["vendors_deferred"] == 1
        assert summary["api_calls"] == 0
        assert summary["status_breakdown"][STATUS_RESOLVED_SOURCE_UEI] == 1
        assert summary["status_breakdown"][STATUS_DEFERRED_API] == 1

    def test_transport_circuit_breaker_stops_residual(self, tmp_path, monkeypatch):
        self._master(
            tmp_path,
            [
                {"vendor_name": f"Vendor {i}", "obligated_amount": "1", "recipient_uei": ""}
                for i in range(5)
            ],
        )
        monkeypatch.setattr(se, "get_sam_api_key", lambda: "KEY")
        monkeypatch.setattr(se, "sam_lookup_by_name", lambda *a, **k: (None, True))
        monkeypatch.setattr(se, "usaspending_lookup", lambda *a, **k: (None, True))
        monkeypatch.setattr(se.time, "sleep", lambda *a, **k: None)
        summary = se.run(
            root=tmp_path,
            use_api=True,
            max_api=5,
            circuit_breaker_failures=2,
        )
        assert summary["api_calls"] == 2
        assert summary["stopped_reason"] == "transport_circuit_open"

    def test_source_uei_keeps_existing_parent_metadata(self, tmp_path):
        self._master(
            tmp_path,
            [
                {
                    "vendor_name": "Acme Inc",
                    "obligated_amount": "500",
                    "recipient_uei": "ACMEUEI00001",
                }
            ],
        )
        output_dir = tmp_path / "data" / "staging" / "processed" / "enrichment"
        output_dir.mkdir(parents=True)
        with (output_dir / "vendor_uei_index.csv").open("w", newline="") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "vendor_name",
                    "total_value",
                    "uei",
                    "cage",
                    "parent_uei",
                    "parent_name",
                    "resolution_status",
                ],
            )
            writer.writeheader()
            writer.writerow(
                {
                    "vendor_name": "Acme Inc",
                    "total_value": "500",
                    "uei": "ACMEUEI00001",
                    "cage": "12345",
                    "parent_uei": "PARENTUEI001",
                    "parent_name": "Acme Parent",
                    "resolution_status": "RESOLVED_SAM",
                }
            )
        se.run(root=tmp_path, resume=True)
        with (output_dir / "vendor_uei_index.csv").open() as source_file:
            rows = list(csv.DictReader(source_file))
        assert rows[0]["cage"] == "12345"
        assert rows[0]["parent_uei"] == "PARENTUEI001"
