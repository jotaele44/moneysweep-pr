"""Tests for download_fsrs — FSRS subaward data via USAspending fallback."""

import pytest
import pandas as pd
from unittest.mock import patch

from scripts.download_fsrs import run, _derive_from_subaward_master, FSRS_COLUMNS


@pytest.mark.unit
def test_run_returns_cached_when_file_has_data(tmp_path):
    """run() skips download when output file already has data rows."""
    out_path = tmp_path / "pr_fsrs_subawards.csv"
    pd.DataFrame([{"subaward_id": "X"}]).to_csv(out_path, index=False)

    with patch("scripts.download_fsrs.OUT_PATH", out_path):
        result = run(force=False)

    assert result["status"] == "cached"
    assert result["rows"] == 1


@pytest.mark.unit
def test_run_force_bypasses_cache(tmp_path):
    """run(force=True) re-fetches even when cached file exists."""
    out_path = tmp_path / "pr_fsrs_subawards.csv"
    pd.DataFrame([{"subaward_id": "X"}]).to_csv(out_path, index=False)

    mock_df = pd.DataFrame(columns=FSRS_COLUMNS)

    with (
        patch("scripts.download_fsrs.OUT_PATH", out_path),
        patch("scripts.download_fsrs._fetch_via_usaspending", return_value=mock_df),
        patch("scripts.download_fsrs.SUBAWARD_MASTER", tmp_path / "nonexistent.csv"),
    ):
        result = run(force=True)

    assert result["status"] == "manual_required"


@pytest.mark.unit
def test_run_usaspending_strategy_writes_file(tmp_path):
    """run() writes output and returns ok_usaspending_api when API succeeds."""
    out_path = tmp_path / "pr_fsrs_subawards.csv"
    mock_df = pd.DataFrame([{col: "x" for col in FSRS_COLUMNS} for _ in range(5)])

    with (
        patch("scripts.download_fsrs.OUT_PATH", out_path),
        patch("scripts.download_fsrs._fetch_via_usaspending", return_value=mock_df),
    ):
        result = run(force=True)

    assert result["status"] == "ok_usaspending_api"
    assert result["rows"] == 5
    assert out_path.exists()


@pytest.mark.unit
def test_run_derives_from_master_when_api_fails(tmp_path):
    """run() falls back to deriving from pr_subawards_master.csv when API fails."""
    out_path = tmp_path / "pr_fsrs_subawards.csv"
    master_path = tmp_path / "pr_subawards_master.csv"
    pd.DataFrame(
        [
            {
                "subaward_id": "M1",
                "prime_award_id": "PA1",
                "prime_award_generated_internal_id": "CONT1",
                "recipient_name": "Vendor A",
                "sub_recipient_uei": "UEITEST01",
                "sub_award_amount": "5000",
                "sub_award_date": "2023-01-01",
                "award_category": "subaward",
                "place_of_performance_state": "PR",
            }
        ]
    ).to_csv(master_path, index=False)

    with (
        patch("scripts.download_fsrs.OUT_PATH", out_path),
        patch("scripts.download_fsrs.SUBAWARD_MASTER", master_path),
        patch("scripts.download_fsrs._fetch_via_usaspending", side_effect=Exception("blocked")),
    ):
        result = run(force=True)

    assert result["status"] == "ok_derived_master"
    assert result["rows"] == 1


@pytest.mark.unit
def test_derive_from_subaward_master_handles_missing_file(tmp_path):
    """_derive_from_subaward_master returns None when master file does not exist."""
    with patch("scripts.download_fsrs.SUBAWARD_MASTER", tmp_path / "nosuchfile.csv"):
        result = _derive_from_subaward_master()
    assert result is None


@pytest.mark.unit
def test_run_manual_required_writes_header_only(tmp_path):
    """run() writes header-only CSV and returns manual_required when all strategies fail."""
    out_path = tmp_path / "pr_fsrs_subawards.csv"

    with (
        patch("scripts.download_fsrs.OUT_PATH", out_path),
        patch("scripts.download_fsrs.SUBAWARD_MASTER", tmp_path / "nosuchfile.csv"),
        patch("scripts.download_fsrs._fetch_via_usaspending", side_effect=Exception("blocked")),
    ):
        result = run(force=True)

    assert result["status"] == "manual_required"
    assert result["rows"] == 0
    assert out_path.exists()
    df = pd.read_csv(out_path)
    assert list(df.columns) == FSRS_COLUMNS
    assert len(df) == 0
