"""Focused tests for scripts.ingest_hud_drgr_exports — empty/missing manual drop.

Verifies that an empty (or absent) data/manual/hud_drgr/ does NOT raise
ValueError: 'If using all scalar values, you must pass an index' and instead
returns a clean manual_required status. Also verifies that unrelated files
under data/raw/ (e.g. Follow the Money, FEC, documents) are filtered out and
not misclassified as HUD DRGR exports.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from scripts.ingest_hud_drgr_exports import _looks_like_hud_drgr, run


def _make_tmp_root(tmp_path: Path) -> Path:
    """Create the minimum directory layout the producer scans."""
    (tmp_path / "data" / "manual" / "hud_drgr").mkdir(parents=True)
    (tmp_path / "data" / "raw").mkdir(parents=True)
    (tmp_path / "data" / "normalized").mkdir(parents=True)
    return tmp_path


def test_empty_manual_drop_returns_manual_required(tmp_path):
    root = _make_tmp_root(tmp_path)
    result = run(root=root, force=True)
    assert result["status"] == "manual_required"
    assert result["activity_rows"] == 0
    assert result["drawdown_rows"] == 0
    assert result["appropriation_rows"] == 0
    # expected_outputs should exist as empty parquets so downstream is happy.
    for name in ("hud_drgr_activities.parquet",
                 "hud_drgr_drawdowns.parquet",
                 "hud_drgr_appropriations.parquet"):
        assert (root / "data" / "normalized" / name).exists()


def test_unrelated_raw_files_are_ignored(tmp_path):
    """A non-HUD CSV under data/raw/<subdir>/ must not be processed as HUD DRGR."""
    root = _make_tmp_root(tmp_path)
    unrelated = root / "data" / "raw" / "Follow the Money"
    unrelated.mkdir(parents=True)
    pd.DataFrame({"x": [1, 2, 3]}).to_csv(unrelated / "funding_flows_sf133.csv", index=False)

    result = run(root=root, force=True)
    assert result["status"] == "manual_required"  # no HUD-named file present


def test_looks_like_hud_drgr_filter():
    assert _looks_like_hud_drgr(Path("data/manual/hud_drgr/something.xlsx"))
    assert _looks_like_hud_drgr(Path("data/raw/HUD DRGR (all PR grantees).xls"))
    assert _looks_like_hud_drgr(Path("data/raw/anywhere/cdbg_dr_export.csv"))
    assert not _looks_like_hud_drgr(Path("data/raw/Follow the Money/funding_flows_sf133.csv"))
    assert not _looks_like_hud_drgr(Path("data/raw/FEC/efile-2026.csv"))
