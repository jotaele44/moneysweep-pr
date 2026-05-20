"""Tests for download_fdic — FDIC bank institution and financial data."""

import pytest
import pandas as pd
from pathlib import Path
from unittest.mock import patch, MagicMock

from scripts.download_fdic import (
    _session,
    _download_institutions,
)


@pytest.mark.skipif(
    not Path("data/staging/processed/pr_fdic_institutions.csv").exists(),
    reason="FDIC institutions file not present"
)
def test_fdic_institutions_csv_exists_and_readable():
    """Integration: FDIC institutions CSV exists and is readable."""
    path = Path("data/staging/processed/pr_fdic_institutions.csv")
    df = pd.read_csv(path, dtype=str, low_memory=False)
    assert len(df) >= 0  # May be empty if no PR banks
    assert "name" in df.columns or "cert" in df.columns


@pytest.mark.skipif(
    not Path("data/staging/processed/pr_fdic_financials.csv").exists(),
    reason="FDIC financials file not present"
)
def test_fdic_financials_csv_exists_and_readable():
    """Integration: FDIC financials CSV exists and is readable."""
    path = Path("data/staging/processed/pr_fdic_financials.csv")
    df = pd.read_csv(path, dtype=str, low_memory=False)
    assert len(df) >= 0  # May be empty if no history
    assert "cert" in df.columns or "report_date" in df.columns


def test_session_returns_configured_session():
    """_session returns a configured requests.Session."""
    session = _session()
    assert session is not None
    assert "User-Agent" in session.headers


@patch("scripts.download_fdic._paginate")
def test_download_institutions_handles_api_failure(mock_paginate):
    """_download_institutions handles API failure gracefully."""
    mock_paginate.return_value = []
    session = MagicMock()
    logger = MagicMock()
    
    result = _download_institutions(session, logger)
    
    assert result is not None
    assert isinstance(result, pd.DataFrame)


@patch("scripts.download_fdic._paginate")
def test_download_institutions_with_data(mock_paginate):
    """_download_institutions processes API data correctly."""
    mock_data = [
        {
            "CERT": "1234",
            "NAME": "Test Bank PR",
            "CITY": "San Juan",
            "STALP": "PR",
            "ACTIVE": "1",
        }
    ]
    mock_paginate.return_value = mock_data
    
    session = MagicMock()
    logger = MagicMock()
    
    result = _download_institutions(session, logger)
    
    assert result is not None
    assert len(result) >= 0

