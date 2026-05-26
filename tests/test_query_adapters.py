"""Adapter tests with injected fake sessions (no real HTTP)."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd
import pytest

from contract_sweeper.query.adapters._stub import NotImplementedAdapter
from contract_sweeper.query.adapters.fec import FECPRAdapter
from contract_sweeper.query.adapters.nih import NIHReporterAdapter, build_payload as nih_build_payload
from contract_sweeper.query.adapters.openfema import (
    OpenFEMAHmgpAdapter,
    OpenFEMAPaAdapter,
    build_filter,
    build_hmgp_filter,
)
from contract_sweeper.query.adapters.sbir import SBIRAdapter
from contract_sweeper.query.adapters.usaspending import (
    USAspendingGrantsAdapter,
    USAspendingPrimeAdapter,
    USAspendingSubawardsAdapter,
    _build_filters,
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


# ---------------------------------------------------------------------------
# USAspending subawards
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_usaspending_subawards_payload_includes_subawards_flag():
    filters = _build_filters(
        Query(municipalities=("San Juan",), fiscal_years=(2024,)),
        root=REPO_ROOT,
        type_codes=["A", "B", "C", "D", "02", "03", "04", "05"],
        subawards=True,
    )
    assert filters["subawards"] is True
    assert {"country": "USA", "state": "PR", "county": "127"} in filters["place_of_performance_locations"]


@pytest.mark.unit
def test_usaspending_subawards_adapter_fetches_with_subaward_fields():
    session = MagicMock()
    session.post.return_value = _mock_response(
        {
            "results": [{"Sub-Award ID": "SUB-1", "Sub-Awardee Name": "X", "Place of Performance City": "SAN JUAN"}],
            "page_metadata": {"hasNext": False},
        }
    )
    adapter = USAspendingSubawardsAdapter(root=REPO_ROOT, session=session)
    df = adapter.fetch(Query(municipalities=("San Juan",), fiscal_years=(2024,)))
    sent_payload = session.post.call_args.kwargs["json"]
    assert sent_payload["filters"]["subawards"] is True
    assert "Sub-Award ID" in sent_payload["fields"]
    assert len(df) == 1


# ---------------------------------------------------------------------------
# USAspending grants (registered as `grants_gov`)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_usaspending_grants_uses_grant_type_codes():
    adapter = USAspendingGrantsAdapter(root=REPO_ROOT, session=MagicMock())
    adapter._session.post.return_value = _mock_response(
        {"results": [], "page_metadata": {"hasNext": False}}
    )
    adapter.fetch(Query(fiscal_years=(2024,)))
    sent_payload = adapter._session.post.call_args.kwargs["json"]
    assert sent_payload["filters"]["award_type_codes"] == ["02", "03", "04", "05"]
    assert sent_payload["filters"].get("subawards") is None


# ---------------------------------------------------------------------------
# OpenFEMA HMGP
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_openfema_hmgp_filter_uses_state_code():
    f = build_hmgp_filter(Query())
    assert f == "stateCode eq 'PR'"


@pytest.mark.unit
def test_openfema_hmgp_fetch_paginates():
    big = [{"disasterNumber": str(i), "stateCode": "PR"} for i in range(1000)]
    short = [{"disasterNumber": "1000", "stateCode": "PR"}]
    session = MagicMock()
    session.get.side_effect = [
        _mock_response({"HazardMitigationGrantProgramDisasterSummaries": big}),
        _mock_response({"HazardMitigationGrantProgramDisasterSummaries": short}),
    ]
    adapter = OpenFEMAHmgpAdapter(root=REPO_ROOT, session=session)
    df = adapter.fetch(Query())
    assert len(df) == 1001


# ---------------------------------------------------------------------------
# NIH Reporter
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_nih_payload_pins_pr_state_and_fiscal_years():
    payload = nih_build_payload(Query(fiscal_years=(2024, 2023)), offset=0)
    assert payload["criteria"]["org_state"] == ["PR"]
    assert payload["criteria"]["fiscal_years"] == [2023, 2024]
    assert payload["limit"] == 500


@pytest.mark.unit
def test_nih_fetch_paginates_via_offset():
    session = MagicMock()
    session.post.side_effect = [
        _mock_response(
            {
                "results": [{"ProjectNum": "R01CA001", "OrgCity": "SAN JUAN"}] * 500,
                "meta": {"total": 750},
            }
        ),
        _mock_response(
            {
                "results": [{"ProjectNum": "R01CA002", "OrgCity": "SAN JUAN"}] * 250,
                "meta": {"total": 750},
            }
        ),
    ]
    adapter = NIHReporterAdapter(root=REPO_ROOT, session=session)
    df = adapter.fetch(Query(fiscal_years=(2024,)))
    assert len(df) == 750
    assert session.post.call_count == 2


# ---------------------------------------------------------------------------
# SBIR
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_sbir_fetch_uses_first_endpoint_when_it_returns_records():
    session = MagicMock()
    session.get.side_effect = [
        _mock_response({"totalCount": 1, "data": [{"award_amount": "100"}]}),
    ]
    adapter = SBIRAdapter(root=REPO_ROOT, session=session)
    df = adapter.fetch(Query())
    assert len(df) == 1
    # Should have used api.sbir.gov, not the fallback.
    args, kwargs = session.get.call_args
    assert args[0] == "https://api.sbir.gov/public/awards"
    assert kwargs["params"]["state"] == "PR"


@pytest.mark.unit
def test_sbir_fetch_handles_list_response():
    session = MagicMock()
    session.get.return_value = _mock_response([{"award_amount": "5"}, {"award_amount": "10"}])
    adapter = SBIRAdapter(root=REPO_ROOT, session=session)
    df = adapter.fetch(Query())
    assert len(df) == 2


# ---------------------------------------------------------------------------
# Per-agency USAspending grant adapters
# ---------------------------------------------------------------------------


from contract_sweeper.query.adapters.usaspending import (  # noqa: E402
    DOEGrantsAdapter,
    DOJGrantsAdapter,
    DOTGrantsAdapter,
    EDGrantsAdapter,
    EPAGrantsAdapter,
    HHSGrantsAdapter,
    OIAGrantsAdapter,
    USDAGrantsAdapter,
)


AGENCY_GRANT_ADAPTERS = [
    (EPAGrantsAdapter, "epa_grants", "Environmental Protection Agency"),
    (DOTGrantsAdapter, "dot_grants", "Department of Transportation"),
    (EDGrantsAdapter, "ed_grants", "Department of Education"),
    (HHSGrantsAdapter, "hhs_grants", "Department of Health and Human Services"),
    (DOEGrantsAdapter, "doe_grants", "Department of Energy"),
    (DOJGrantsAdapter, "doj_grants", "Department of Justice"),
    (USDAGrantsAdapter, "usda_grants", "Department of Agriculture"),
    (OIAGrantsAdapter, "oia_grants", "Department of the Interior"),
]


@pytest.mark.unit
@pytest.mark.parametrize("cls,sid,agency", AGENCY_GRANT_ADAPTERS)
def test_agency_grants_adapter_injects_correct_agency(cls, sid, agency):
    adapter = cls(root=REPO_ROOT, session=MagicMock())
    payload = adapter._payload(Query(fiscal_years=(2024,)), 1)
    assert adapter.source_id == sid
    assert payload["filters"]["agencies"] == [
        {"type": "awarding", "tier": "toptier", "name": agency}
    ]
    assert payload["filters"]["award_type_codes"] == ["02", "03", "04", "05"]


@pytest.mark.unit
def test_agency_grants_adapter_respects_caller_supplied_agency():
    """If the caller already specified agencies, the adapter doesn't override."""
    adapter = EPAGrantsAdapter(root=REPO_ROOT, session=MagicMock())
    payload = adapter._payload(Query(agencies=("Custom Agency",)), 1)
    # The caller's agency wins, not the adapter's default.
    assert payload["filters"]["agencies"][0]["name"] == "Custom Agency"


# ---------------------------------------------------------------------------
# LDA
# ---------------------------------------------------------------------------


from contract_sweeper.query.adapters.lda import LDAAdapter, build_params as lda_build_params  # noqa: E402


@pytest.mark.unit
def test_lda_build_params_includes_state_param_and_page_size():
    params = lda_build_params(Query(), state_param="client_state", page=2)
    assert params["client_state"] == "PR"
    assert params["page"] == 2
    assert params["page_size"] == 100
    assert "filing_year" not in params


@pytest.mark.unit
def test_lda_build_params_with_fiscal_years_sets_filing_year():
    params = lda_build_params(Query(fiscal_years=(2022, 2024, 2023)), state_param="registrant_state", page=1)
    assert params["registrant_state"] == "PR"
    assert params["filing_year"] == 2024  # most recent


@pytest.mark.unit
def test_lda_fetch_dedupes_across_client_and_registrant_passes():
    session = MagicMock()
    # client_state pass returns 2 filings; registrant_state pass returns one duplicate + one new.
    session.get.side_effect = [
        _mock_response(
            {
                "results": [
                    {"filing_uuid": "abc", "filing_type": "Q1"},
                    {"filing_uuid": "def", "filing_type": "Q2"},
                ],
                "next": None,
            }
        ),
        _mock_response(
            {
                "results": [
                    {"filing_uuid": "abc", "filing_type": "Q1"},  # duplicate
                    {"filing_uuid": "ghi", "filing_type": "Q3"},  # new
                ],
                "next": None,
            }
        ),
    ]
    adapter = LDAAdapter(root=REPO_ROOT, session=session)
    df = adapter.fetch(Query())
    # Two passes were made.
    assert session.get.call_count == 2
    # Dedup: 3 unique uuids (abc, def, ghi).
    assert len(df) == 3
    assert set(df["filing_uuid"]) == {"abc", "def", "ghi"}


@pytest.mark.unit
def test_lda_session_includes_token_when_api_key_set():
    """When an explicit api_key is passed, the session sends Authorization header."""
    adapter = LDAAdapter(root=REPO_ROOT, api_key="my-test-token")
    session = adapter._get_session()
    assert session.headers["Authorization"] == "Token my-test-token"


@pytest.mark.unit
def test_lda_session_omits_token_when_no_api_key(monkeypatch):
    monkeypatch.delenv("LDA_API_KEY", raising=False)
    adapter = LDAAdapter(root=REPO_ROOT)
    session = adapter._get_session()
    assert "Authorization" not in session.headers


# ---------------------------------------------------------------------------
# NSF Awards
# ---------------------------------------------------------------------------


from contract_sweeper.query.adapters.nsf import NSFAwardsAdapter, build_params as nsf_build_params  # noqa: E402


@pytest.mark.unit
def test_nsf_build_params_pins_awardee_state_to_pr():
    params = nsf_build_params(Query(), offset=1)
    assert params["awardeeStateCode"] == "PR"
    assert params["offset"] == 1
    assert "awardeeName" in params["printFields"]
    assert "fundsObligatedAmt" in params["printFields"]


@pytest.mark.unit
def test_nsf_build_params_with_fiscal_years_sets_date_window():
    params = nsf_build_params(Query(fiscal_years=(2020, 2024, 2022)), offset=1)
    assert params["dateStart"] == "01/01/2020"
    assert params["dateEnd"] == "12/31/2024"


@pytest.mark.unit
def test_nsf_fetch_paginates_until_short_page():
    full = [{"id": str(i), "awardeeStateCode": "PR"} for i in range(25)]
    short = [{"id": "100", "awardeeStateCode": "PR"}]
    session = MagicMock()
    session.get.side_effect = [
        _mock_response({"response": {"award": full}}),
        _mock_response({"response": {"award": short}}),
    ]
    adapter = NSFAwardsAdapter(root=REPO_ROOT, session=session)
    df = adapter.fetch(Query())
    assert len(df) == 26
    assert session.get.call_count == 2


@pytest.mark.unit
def test_nsf_source_id_matches_registry():
    assert NSFAwardsAdapter.source_id == "research_grants"
