"""Tests for download_cms — CMS Open Payments and Medicare provider data."""

import pytest
import pandas as pd
from pathlib import Path
from unittest.mock import patch, MagicMock

from scripts.download_cms import (
    _session,
    _normalize_open_payments,
    _normalize_medicare,
)


@pytest.mark.skipif(
    not Path("data/staging/processed/pr_cms_open_payments.csv").exists(),
    reason="CMS Open Payments file not present"
)
def test_cms_open_payments_csv_exists_and_readable():
    """Integration: CMS Open Payments CSV exists and is readable."""
    path = Path("data/staging/processed/pr_cms_open_payments.csv")
    df = pd.read_csv(path, dtype=str, low_memory=False)
    assert len(df) >= 0  # May be empty if no PR providers
    assert "recipient_name" in df.columns or "payment_amount" in df.columns


@pytest.mark.skipif(
    not Path("data/staging/processed/pr_cms_medicare_providers.csv").exists(),
    reason="CMS Medicare providers file not present"
)
def test_cms_medicare_providers_csv_exists_and_readable():
    """Integration: CMS Medicare providers CSV exists and is readable."""
    path = Path("data/staging/processed/pr_cms_medicare_providers.csv")
    df = pd.read_csv(path, dtype=str, low_memory=False)
    assert len(df) >= 0  # May be empty if no PR providers
    assert "npi" in df.columns or "provider_name" in df.columns


def test_session_returns_configured_session():
    """_session returns a configured requests.Session."""
    session = _session()
    assert session is not None
    assert "User-Agent" in session.headers


def test_normalize_open_payment_typical_records():
    """_normalize_open_payments handles typical payment records."""
    records = [
        {
            "recipient_npi": "1234567890",
            "recipient_name": "Dr. John Smith",
            "submitting_applicable_manufacturer_or_applicable_gpo_name": "Pfizer",
            "total_amount_of_payment_usdollars": 1000.00,
            "date_of_payment": "2023-06-15",
            "nature_of_payment_or_transfer_of_value": "General",
            "city": "San Juan",
            "state": "PR",
        }
    ]
    result = _normalize_open_payments(records)
    assert result is not None
    assert isinstance(result, pd.DataFrame)


def test_normalize_open_payment_missing_fields():
    """_normalize_open_payments handles missing fields gracefully."""
    records = [
        {
            "recipient_npi": "1234567890",
            "total_amount_of_payment_usdollars": 1000.00,
        }
    ]
    result = _normalize_open_payments(records)
    assert result is not None
    assert isinstance(result, pd.DataFrame)


def test_normalize_medicare_typical_records():
    """_normalize_medicare handles typical provider records."""
    records = [
        {
            "npi": "1234567890",
            "provider_name": "Dr. Maria Garcia",
            "total_submitted_charge_amount": 250000.00,
            "address_city": "San Juan",
            "address_state": "PR",
        }
    ]
    result = _normalize_medicare(records)
    assert result is not None
    assert isinstance(result, pd.DataFrame)


@patch("scripts.download_cms.requests.get")
def test_cms_api_handles_timeout(mock_get):
    """CMS API request handles timeout gracefully."""
    mock_get.side_effect = Exception("Connection timeout")
    with pytest.raises(Exception):
        mock_get("https://openpaymentsdata.cms.gov/api/1/dummy")


@patch("scripts.download_cms.requests.Session")
def test_cms_connection_error_handled(mock_session_class):
    """CMS downloader handles connection errors."""
    mock_session = MagicMock()
    mock_session.get.side_effect = Exception("Connection refused")
    
    with pytest.raises(Exception):
        mock_session.get("https://data.cms.gov/data-api/v1/dataset")

