"""Adapter tests with injected fake sessions (no real HTTP)."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd
import pytest

from contract_sweeper.query.adapters._stub import NotImplementedAdapter
from contract_sweeper.query.adapters.fec import FECPRAdapter
from contract_sweeper.query.adapters.openfema import OpenFEMAPaAdapter, build_filter
from contract_sweeper.query.adapters.usaspending import (
    USAspendingPrimeAdapter,
    _municipalities_to_county_suffixes,
    build_payload,
)
from contract_sweeper.query.types import CredentialMissing, ManualOnlyError, Query

REPO_ROOT = Path(__file__).resolve().parents[1]


def _mock_response(payload: dict) -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = payload
    resp.raise_for_status = MagicMock()
    return resp


# ---------------------------------------------------------------------------
# USAspending
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_usaspending_municipalities_to_county_suffixes_resolves_san_juan():
    out = _municipalities_to_county_suffixes(("San Juan",), REPO_ROOT)
    assert out == ["127"]


@pytest.mark.unit
def test_usaspending_municipalities_to_county_suffixes_handles_fips_input():
    out = _municipalities_to_county_suffixes(("72113",), REPO_ROOT)
    assert out == ["113"]  # Ponce


@pytest.mark.unit
def test_usaspending_municipalities_to_county_suffixes_skips_unknown():
    out = _municipalities_to_county_suffixes(("Atlantis",), REPO_ROOT)
    assert out == []


@pytest.mark.unit
def test_usaspending_payload_includes_pr_state_and_county_suffix():
    payload = build_payload(
        Query(municipalities=("San Juan",), fiscal_years=(2024,)),
        root=REPO_ROOT,
    )
    locations = payload["filters"]["place_of_performance_locations"]
    assert {"country": "USA", "state": "PR", "county": "127"} in locations
    assert payload["filters"]["time_period"] == [{"start_date": "2023-10-01", "end_date": "2024-09-30"}]


@pytest.mark.unit
def test_usaspending_payload_omits_county_when_no_municipalities():
    payload = build_payload(Query(fiscal_years=(2024,)), root=REPO_ROOT)
    locations = payload["filters"]["place_of_performance_locations"]
    assert locations == [{"country": "USA", "state": "PR"}]


@pytest.mark.unit
def test_usaspending_fetch_paginates_and_returns_dataframe():
    session = MagicMock()
    session.post.side_effect = [
        _mock_response(
            {
                "results": [
                    {"Award ID": "1", "Recipient Name": "A", "Place of Performance City": "SAN JUAN"},
                    {"Award ID": "2", "Recipient Name": "B", "Place of Performance City": "SAN JUAN"},
                ],
                "page_metadata": {"hasNext": True},
            }
        ),
        _mock_response(
            {
                "results": [{"Award ID": "3", "Recipient Name": "C", "Place of Performance City": "SAN JUAN"}],
                "page_metadata": {"hasNext": False},
            }
        ),
    ]
    adapter = USAspendingPrimeAdapter(root=REPO_ROOT, session=session)
    df = adapter.fetch(Query(municipalities=("San Juan",), fiscal_years=(2024,)))
    assert len(df) == 3
    assert session.post.call_count == 2


# ---------------------------------------------------------------------------
# OpenFEMA
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_openfema_filter_includes_state_and_county_fips():
    f = build_filter(Query(municipalities=("San Juan",)), root=REPO_ROOT)
    assert "state eq 'PR'" in f
    assert "countyFips eq '72127'" in f


@pytest.mark.unit
def test_openfema_filter_with_no_municipalities_is_state_only():
    f = build_filter(Query(), root=REPO_ROOT)
    assert f == "state eq 'PR'"


@pytest.mark.unit
def test_openfema_filter_with_fiscal_years_includes_declarationFY():
    f = build_filter(Query(fiscal_years=(2024, 2023)), root=REPO_ROOT)
    assert "declarationFY eq 2023" in f
    assert "declarationFY eq 2024" in f


@pytest.mark.unit
def test_openfema_fetch_paginates_until_short_page():
    big_page = [{"id": i, "countyFips": "72127"} for i in range(1000)]
    short_page = [{"id": 1000, "countyFips": "72127"}]
    session = MagicMock()
    session.get.side_effect = [
        _mock_response({"PublicAssistanceFundedProjectsDetails": big_page}),
        _mock_response({"PublicAssistanceFundedProjectsDetails": short_page}),
    ]
    adapter = OpenFEMAPaAdapter(root=REPO_ROOT, session=session)
    df = adapter.fetch(Query(municipalities=("San Juan",)))
    assert len(df) == 1001
    assert session.get.call_count == 2


# ---------------------------------------------------------------------------
# FEC
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_fec_raises_credential_missing_when_env_unset(monkeypatch):
    monkeypatch.delenv("FEC_API_KEY", raising=False)
    adapter = FECPRAdapter(root=REPO_ROOT)
    with pytest.raises(CredentialMissing) as excinfo:
        adapter.fetch(Query())
    assert excinfo.value.env_var == "FEC_API_KEY"


@pytest.mark.unit
def test_fec_uses_explicit_api_key_when_provided():
    session = MagicMock()
    session.get.return_value = _mock_response(
        {"results": [{"sub_id": "1", "contributor_city": "SAN JUAN"}], "pagination": {"page": 1, "pages": 1}}
    )
    adapter = FECPRAdapter(root=REPO_ROOT, session=session, api_key="testkey")
    df = adapter.fetch(Query())
    assert len(df) == 1
    # Adapter should have included contributor_state=PR in params.
    _, kwargs = session.get.call_args
    assert kwargs["params"]["contributor_state"] == "PR"


# ---------------------------------------------------------------------------
# Stub
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_stub_adapter_raises_manual_only_with_producer_script():
    adapter = NotImplementedAdapter(root=REPO_ROOT, source_id="lda")
    with pytest.raises(ManualOnlyError) as excinfo:
        adapter.fetch(Query())
    assert excinfo.value.source_id == "lda"
    assert "download_lda.py" in str(excinfo.value)
