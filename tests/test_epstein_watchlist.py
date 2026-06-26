"""Tests for the epstein_pr_case watchlist (flag manifest + matcher + separation).

The watchlist is a flagged cross-reference list, NOT a public-money source. These
tests assert the manifest is well-formed and regenerates deterministically, the
matcher flags known entities without over-flagging, the raw records live under
data/watchlists/ (quarantined), and the watchlist is absent from the source
registry.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.build_watchlist_flags import OUT, build
from scripts.watchlist import flagged_entities, load_watchlist, match

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = REPO_ROOT / "data" / "watchlists" / "epstein_pr_case"


def test_quarantined_records_live_under_watchlists():
    files = sorted(p.name for p in RAW_DIR.glob("EP_PR_PRBank_*.csv"))
    assert files == [
        "EP_PR_PRBank_Summary_ByAccount.csv",
        "EP_PR_PRBank_Summary_ByEntity.csv",
        "EP_PR_PRBank_Summary_ByYear.csv",
        "EP_PR_PRBank_Wire_Ledger_ALL.csv",
    ]
    assert (RAW_DIR / "README.md").exists()


def test_manifest_is_well_formed():
    wl = load_watchlist("epstein_pr_case")
    assert wl["watchlist_id"] == "epstein_pr_case"
    assert wl["status"] == "flagged_reference_only"
    assert wl["do_not_materialize"] is True
    assert wl["flagged_entities"], "expected at least one flagged entity"
    assert wl["transaction_count"] == len(wl["transactions"])


def test_manifest_regenerates_identically():
    committed = json.loads(OUT.read_text(encoding="utf-8"))
    assert build() == committed, (
        "registries/watchlists/epstein_pr_case.json is stale — regenerate with: "
        "python3 scripts/build_watchlist_flags.py"
    )


def test_matcher_flags_known_entities_without_overflagging():
    assert match("JEFFREY E EPSTEIN", "epstein_pr_case")
    assert match("Nautilus, Inc.", "epstein_pr_case")
    assert match("GREAT ST JIM LLC", "epstein_pr_case")
    # Unrelated public-money entities must not be flagged.
    assert not match("PRASA", "epstein_pr_case")
    assert not match("Department of the Army", "epstein_pr_case")
    # Generic suffixes must not over-flag.
    assert not match("INC", "epstein_pr_case")
    assert not match("LLC", "epstein_pr_case")


def test_epstein_known_entities_present():
    ents = flagged_entities("epstein_pr_case")
    assert "JEFFREY E EPSTEIN" in ents
    assert "NAUTILUS INC" in ents


def test_watchlist_not_in_source_registry():
    from moneysweep.runtime.source_registry import all_sources

    ids = {s["source_id"] for s in all_sources(REPO_ROOT)}
    assert "epstein_pr_case" not in ids
    # And the quarantined wire-ledger output is not a declared expected_output anywhere.
    for s in all_sources(REPO_ROOT):
        assert "pr_ftm_wire_ledger.csv" not in (s.get("expected_outputs") or [])
