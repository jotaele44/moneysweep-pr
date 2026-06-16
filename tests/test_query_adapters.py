"""Adapter tests with injected fake sessions (no real HTTP)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from contract_sweeper.query.adapters._stub import NotImplementedAdapter
from contract_sweeper.query.adapters.fec import FECPRAdapter
from contract_sweeper.query.adapters.nih import (
    NIHReporterAdapter,
    build_payload as nih_build_payload,
)
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
    assert payload["filters"]["time_period"] == [
        {"start_date": "2023-10-01", "end_date": "2024-09-30"}
    ]


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
                    {
                        "Award ID": "1",
                        "Recipient Name": "A",
                        "Place of Performance City": "SAN JUAN",
                    },
                    {
                        "Award ID": "2",
                        "Recipient Name": "B",
                        "Place of Performance City": "SAN JUAN",
                    },
                ],
                "page_metadata": {"hasNext": True},
            }
        ),
        _mock_response(
            {
                "results": [
                    {
                        "Award ID": "3",
                        "Recipient Name": "C",
                        "Place of Performance City": "SAN JUAN",
                    }
                ],
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
        {
            "results": [{"sub_id": "1", "contributor_city": "SAN JUAN"}],
            "pagination": {"page": 1, "pages": 1},
        }
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
    assert "fetch_lda_gov.py" in str(excinfo.value)


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
    assert {"country": "USA", "state": "PR", "county": "127"} in filters[
        "place_of_performance_locations"
    ]


@pytest.mark.unit
def test_usaspending_subawards_adapter_fetches_with_subaward_fields():
    session = MagicMock()
    session.post.return_value = _mock_response(
        {
            "results": [
                {
                    "Sub-Award ID": "SUB-1",
                    "Sub-Awardee Name": "X",
                    "Place of Performance City": "SAN JUAN",
                }
            ],
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
    params = lda_build_params(
        Query(fiscal_years=(2022, 2024, 2023)), state_param="registrant_state", page=1
    )
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


# ---------------------------------------------------------------------------
# OpenFEMA NFIP claims
# ---------------------------------------------------------------------------


from contract_sweeper.query.adapters.openfema import OpenFEMANfipClaimsAdapter  # noqa: E402


@pytest.mark.unit
def test_nfip_claims_adapter_uses_state_pr_filter_and_data_key():
    big_page = [{"reportedCity": "San Juan", "amountPaidOnBuildingClaim": "100"}] * 1000
    short_page = [{"reportedCity": "Ponce", "amountPaidOnBuildingClaim": "200"}]
    session = MagicMock()
    session.get.side_effect = [
        _mock_response({"FimaNfipClaims": big_page}),
        _mock_response({"FimaNfipClaims": short_page}),
    ]
    adapter = OpenFEMANfipClaimsAdapter(root=REPO_ROOT, session=session)
    df = adapter.fetch(Query(municipalities=("San Juan",)))
    assert len(df) == 1001
    # Both calls carried state=PR and the san-juan county fips clause.
    for call_args in session.get.call_args_list:
        params = call_args.kwargs.get("params") or call_args[1]["params"]
        assert "state eq 'PR'" in params["$filter"]
        assert "countyFips eq '72127'" in params["$filter"]


# ---------------------------------------------------------------------------
# USAspending program-narrow adapters (SLFRF / HAF / EXIM)
# ---------------------------------------------------------------------------


from contract_sweeper.query.adapters.usaspending import (  # noqa: E402
    DIRECT_PAYMENT_TYPE_CODES,
    EXIMBankAdapter,
    HAFAdapter,
    LOAN_TYPE_CODES,
    SLFRFAdapter,
)


@pytest.mark.unit
@pytest.mark.parametrize(
    "adapter_cls,expected_agency,expected_program",
    [
        (SLFRFAdapter, "Department of the Treasury", None),
        (HAFAdapter, "Department of the Treasury", ["21.026"]),
        (EXIMBankAdapter, "Export-Import Bank of the United States", None),
    ],
)
def test_usaspending_narrow_adapters_inject_agency_and_program(
    adapter_cls, expected_agency, expected_program
):
    adapter = adapter_cls(root=REPO_ROOT)
    payload = adapter._payload(Query(municipalities=("San Juan",)), page=1)
    agencies = payload["filters"]["agencies"]
    assert agencies[0]["name"] == expected_agency
    if expected_program is None:
        assert "program_numbers" not in payload["filters"]
    else:
        assert payload["filters"]["program_numbers"] == expected_program


@pytest.mark.unit
def test_haf_adapter_award_type_codes_are_grants_only():
    adapter = HAFAdapter(root=REPO_ROOT)
    payload = adapter._payload(Query(), page=1)
    assert payload["filters"]["award_type_codes"] == ["02", "03", "04", "05"]


@pytest.mark.unit
def test_exim_adapter_award_type_codes_include_loans():
    adapter = EXIMBankAdapter(root=REPO_ROOT)
    payload = adapter._payload(Query(), page=1)
    codes = payload["filters"]["award_type_codes"]
    for c in DIRECT_PAYMENT_TYPE_CODES + LOAN_TYPE_CODES:
        assert c in codes


@pytest.mark.unit
def test_caller_supplied_agency_overrides_narrow_adapter_default():
    """A caller passing an explicit agency must not get overwritten by the subclass default."""
    adapter = SLFRFAdapter(root=REPO_ROOT)
    payload = adapter._payload(Query(agencies=("Department of Energy",)), page=1)
    names = [a["name"] for a in payload["filters"]["agencies"]]
    assert names == ["Department of Energy"]


# ---------------------------------------------------------------------------
# FDIC
# ---------------------------------------------------------------------------


from contract_sweeper.query.adapters.fdic import FDICInstitutionsAdapter  # noqa: E402


@pytest.mark.unit
def test_fdic_adapter_sends_stalp_pr_filter_and_offset_paginates():
    big = [{"data": {"NAME": f"BANK_{i}", "STALP": "PR"}} for i in range(1000)]
    short = [{"data": {"NAME": "BANK_LAST", "STALP": "PR"}}]
    session = MagicMock()
    session.get.side_effect = [
        _mock_response({"data": big, "meta": {"total": 1001}}),
        _mock_response({"data": short, "meta": {"total": 1001}}),
    ]
    adapter = FDICInstitutionsAdapter(root=REPO_ROOT, session=session)
    df = adapter.fetch(Query())
    assert len(df) == 1001
    for call_args in session.get.call_args_list:
        params = call_args.kwargs.get("params") or call_args[1]["params"]
        assert params["filters"] == "STALP:PR"
    # Offsets should advance.
    offsets = [
        (ca.kwargs.get("params") or ca[1]["params"])["offset"] for ca in session.get.call_args_list
    ]
    assert offsets == [0, 1000]


@pytest.mark.unit
def test_fdic_adapter_returns_empty_df_when_no_records():
    session = MagicMock()
    session.get.return_value = _mock_response({"data": [], "meta": {"total": 0}})
    adapter = FDICInstitutionsAdapter(root=REPO_ROOT, session=session)
    df = adapter.fetch(Query())
    assert df.empty


# ---------------------------------------------------------------------------
# ProPublica Nonprofits
# ---------------------------------------------------------------------------


from contract_sweeper.query.adapters.nonprofits import NonprofitsIRS990Adapter  # noqa: E402


@pytest.mark.unit
def test_nonprofits_adapter_sends_state_pr_and_page_paginates():
    page0 = [{"ein": str(i), "state": "PR"} for i in range(25)]
    page1 = [{"ein": "999", "state": "PR"}]
    session = MagicMock()
    session.get.side_effect = [
        _mock_response({"organizations": page0}),
        _mock_response({"organizations": page1}),
        _mock_response({"organizations": []}),
    ]
    adapter = NonprofitsIRS990Adapter(root=REPO_ROOT, session=session)
    df = adapter.fetch(Query())
    assert len(df) == 26
    pages = [
        (ca.kwargs.get("params") or ca[1]["params"])["page"] for ca in session.get.call_args_list
    ]
    assert pages == [0, 1, 2]
    for ca in session.get.call_args_list:
        params = ca.kwargs.get("params") or ca[1]["params"]
        assert params["state[id]"] == "PR"


@pytest.mark.unit
def test_nonprofits_adapter_attaches_api_key_when_set(monkeypatch):
    monkeypatch.setenv("PROPUBLICA_API_KEY", "test-token")
    adapter = NonprofitsIRS990Adapter(root=REPO_ROOT)
    session = adapter._get_session()
    assert session.headers["X-API-Key"] == "test-token"


@pytest.mark.unit
def test_nonprofits_adapter_omits_api_key_header_when_unset(monkeypatch):
    monkeypatch.delenv("PROPUBLICA_API_KEY", raising=False)
    adapter = NonprofitsIRS990Adapter(root=REPO_ROOT)
    session = adapter._get_session()
    assert "X-API-Key" not in session.headers


# ---------------------------------------------------------------------------
# SBA (PPP + 7(a)/504 disaster loans)
# ---------------------------------------------------------------------------


from contract_sweeper.query.adapters.sba import (  # noqa: E402
    SBALoansAdapter,
    SBAPaycheckProtectionAdapter,
    CKAN_DATASTORE_URL,
    CKAN_PACKAGE_URL,
)


@pytest.mark.unit
@pytest.mark.parametrize(
    "adapter_cls,expected_state_field",
    [
        (SBALoansAdapter, "State"),
        (SBAPaycheckProtectionAdapter, "BorrowerState"),
    ],
)
def test_sba_adapter_discovers_resource_and_filters_state(adapter_cls, expected_state_field):
    session = MagicMock()
    session.get.side_effect = [
        _mock_response(
            {
                "success": True,
                "result": {"resources": [{"id": "abc-resource", "format": "CSV"}]},
            }
        ),
        _mock_response(
            {
                "success": True,
                "result": {"records": [{"LoanID": "1", expected_state_field: "PR"}], "total": 1},
            }
        ),
        _mock_response({"success": True, "result": {"records": [], "total": 1}}),
    ]
    adapter = adapter_cls(root=REPO_ROOT, session=session)
    df = adapter.fetch(Query())
    assert len(df) == 1
    # First call is package_show.
    first_call = session.get.call_args_list[0]
    assert first_call.args[0] == CKAN_PACKAGE_URL or first_call[0][0] == CKAN_PACKAGE_URL
    # Subsequent calls hit datastore_search with the right state filter.
    second_call = session.get.call_args_list[1]
    url = second_call.args[0] if second_call.args else second_call[0][0]
    assert url == CKAN_DATASTORE_URL
    params = second_call.kwargs.get("params") or second_call[1]["params"]
    assert json.loads(params["filters"]) == {expected_state_field: "PR"}
    assert params["resource_id"] == "abc-resource"


@pytest.mark.unit
def test_sba_adapter_returns_empty_when_discovery_fails():
    session = MagicMock()
    # Every package_show + package_search lookup fails.
    session.get.return_value = _mock_response({"success": False, "result": {}})
    adapter = SBALoansAdapter(root=REPO_ROOT, session=session)
    df = adapter.fetch(Query())
    assert df.empty


# ---------------------------------------------------------------------------
# HigherGov supplemental (Batch 6 — required api_key, credential-gated)
# ---------------------------------------------------------------------------


from contract_sweeper.query.adapters.highergov import (  # noqa: E402
    HigherGovSupplementalAdapter,
    HIGHERGOV_BASE,
    PAGE_SIZE as HIGHERGOV_PAGE_SIZE,
)


@pytest.mark.unit
def test_highergov_raises_credential_missing_without_env(monkeypatch):
    monkeypatch.delenv("HIGHERGOV_API_KEY", raising=False)
    session = MagicMock()
    adapter = HigherGovSupplementalAdapter(root=REPO_ROOT, session=session)
    with pytest.raises(CredentialMissing) as excinfo:
        adapter.fetch(Query())
    assert excinfo.value.env_var == "HIGHERGOV_API_KEY"
    assert excinfo.value.source_id == "highergov_supplemental"
    # No HTTP call should have been attempted.
    session.get.assert_not_called()


@pytest.mark.unit
def test_highergov_sends_api_key_query_param_and_search_id(monkeypatch):
    monkeypatch.setenv("HIGHERGOV_API_KEY", "test-key")
    short_page = [{"id": "x", "title": "t"}]
    session = MagicMock()
    session.get.return_value = _mock_response({"results": short_page})
    adapter = HigherGovSupplementalAdapter(root=REPO_ROOT, session=session)
    df = adapter.fetch(Query())
    assert len(df) == 1
    call = session.get.call_args
    url = call.args[0] if call.args else call[0][0]
    params = call.kwargs.get("params") or call[1]["params"]
    assert url == f"{HIGHERGOV_BASE}/contract/"
    assert params["api_key"] == "test-key"
    assert params["search_id"] == HigherGovSupplementalAdapter.search_id
    assert params["page_size"] == HIGHERGOV_PAGE_SIZE


@pytest.mark.unit
def test_highergov_subclass_overrides_resource_and_search_id(monkeypatch):
    monkeypatch.setenv("HIGHERGOV_API_KEY", "test-key")

    class HigherGovOpportunityAdapter(HigherGovSupplementalAdapter):
        resource = "opportunity"
        search_id = "opportunity-search-id"

    session = MagicMock()
    session.get.return_value = _mock_response({"results": []})
    adapter = HigherGovOpportunityAdapter(root=REPO_ROOT, session=session)
    adapter.fetch(Query())
    call = session.get.call_args
    url = call.args[0] if call.args else call[0][0]
    params = call.kwargs.get("params") or call[1]["params"]
    assert url == f"{HIGHERGOV_BASE}/opportunity/"
    assert params["search_id"] == "opportunity-search-id"


@pytest.mark.unit
def test_highergov_paginates_until_short_page(monkeypatch):
    monkeypatch.setenv("HIGHERGOV_API_KEY", "test-key")
    full_page = [{"id": str(i)} for i in range(HIGHERGOV_PAGE_SIZE)]
    short_page = [{"id": "last"}]
    session = MagicMock()
    session.get.side_effect = [
        _mock_response({"results": full_page}),
        _mock_response({"results": short_page}),
    ]
    adapter = HigherGovSupplementalAdapter(root=REPO_ROOT, session=session)
    df = adapter.fetch(Query())
    assert len(df) == HIGHERGOV_PAGE_SIZE + 1
    pages = [
        (ca.kwargs.get("params") or ca[1]["params"])["page"] for ca in session.get.call_args_list
    ]
    assert pages == [1, 2]


# ---------------------------------------------------------------------------
# Registry size check
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_adapter_registry_size_matches_concrete_count():
    from contract_sweeper.query.adapters import ADAPTER_REGISTRY

    # 33 original + 5 USASpending agency+CFDA benefit narrows
    # (va_benefits, wioa, wic, snap_nap, hud_hcv_section8)
    # + usace_civil_works (sub-agency narrow) + fhlb (FDIC SDI),
    # − opencorporates (paid source removed; replaced by gleif_lei/sec_officers).
    assert len(ADAPTER_REGISTRY) == 39
