"""Tests for Batch 7a CMS-family query adapters (mocked HTTP)."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd
import pytest

from contract_sweeper.query.adapters.ckan_metastore import (
    CHIPAdapter,
    CMSOpenPaymentsAdapter,
    MedicaidFMAPAdapter,
    _CKANMetastoreAdapter,
)
from contract_sweeper.query.adapters.cms_socrata import (
    DEFAULT_STATE_CLAUSE,
    MedicareAdvantageAdapter,
    MedicarePartsAdapter,
    SOCRATA_BASE,
)
from contract_sweeper.query.types import Query

REPO_ROOT = Path(__file__).resolve().parents[1]


def _mock_response(payload):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = payload
    resp.raise_for_status = MagicMock()
    return resp


# ---------------------------------------------------------------------------
# CMS Socrata (medicare_advantage, medicare_parts)
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "adapter_cls,expected_ids",
    [
        (MedicareAdvantageAdapter, ("qksd-9k7j", "nu5k-459e", "r9ta-rabe")),
        (MedicarePartsAdapter, ("6i6u-frbu", "w96h-y9mq", "tbcw-ytz8")),
    ],
)
def test_cms_socrata_iterates_each_resource_id(adapter_cls, expected_ids):
    short_page = [{"plan_id": "H1", "state": "PR"}]
    session = MagicMock()
    # Three resources × one short page each ⇒ three GETs returning <PAGE_SIZE rows.
    session.get.side_effect = [_mock_response(short_page) for _ in expected_ids]
    adapter = adapter_cls(root=REPO_ROOT, session=session)
    df = adapter.fetch(Query())
    assert len(df) == len(expected_ids)
    # All three resource URLs hit.
    urls = [
        (ca.args[0] if ca.args else ca[0][0]) for ca in session.get.call_args_list
    ]
    for rid in expected_ids:
        assert any(rid in u for u in urls)
    # Each row tagged with its source_dataset_id.
    assert set(df["source_dataset_id"]) == set(expected_ids)


@pytest.mark.unit
def test_cms_socrata_state_clause_passed_verbatim():
    session = MagicMock()
    session.get.return_value = _mock_response([])
    adapter = MedicareAdvantageAdapter(root=REPO_ROOT, session=session)
    adapter.fetch(Query())
    params = session.get.call_args.kwargs.get("params") or session.get.call_args[1]["params"]
    assert params["$where"] == DEFAULT_STATE_CLAUSE
    assert params["$limit"] == 10000


@pytest.mark.unit
def test_cms_socrata_paginates_until_short_page():
    # 10000-row page then a 5-row page → 2 GETs per resource.
    full = [{"plan_id": str(i), "state": "PR"} for i in range(10000)]
    short = [{"plan_id": "last", "state": "PR"}]
    session = MagicMock()
    # Resource 1: full + short; resources 2 & 3: short only (still terminate).
    session.get.side_effect = [
        _mock_response(full),
        _mock_response(short),
        _mock_response(short),
        _mock_response(short),
    ]
    adapter = MedicareAdvantageAdapter(root=REPO_ROOT, session=session)
    df = adapter.fetch(Query())
    # First resource produced 10001 rows; resources 2 & 3 produced 1 row each.
    assert len(df) == 10003


@pytest.mark.unit
def test_cms_socrata_attaches_app_token_header_when_env_set(monkeypatch):
    monkeypatch.setenv("CMS_APP_TOKEN", "secret-token")
    adapter = MedicareAdvantageAdapter(root=REPO_ROOT)
    session = adapter._get_session()
    assert session.headers["X-App-Token"] == "secret-token"


@pytest.mark.unit
def test_cms_socrata_calls_api_without_token_when_env_unset(monkeypatch):
    monkeypatch.delenv("CMS_APP_TOKEN", raising=False)
    session = MagicMock()
    session.get.return_value = _mock_response([])
    adapter = MedicarePartsAdapter(root=REPO_ROOT, session=session)
    adapter.fetch(Query())  # Must NOT raise CredentialMissing.
    # And the session helper should NOT have an X-App-Token header by default.
    fresh_session = MedicarePartsAdapter(root=REPO_ROOT)._get_session()
    assert "X-App-Token" not in fresh_session.headers


@pytest.mark.unit
def test_cms_socrata_one_resource_failing_doesnt_sink_the_rest():
    short = [{"plan_id": "x", "state": "PR"}]

    def side_effect(*args, **kwargs):
        url = args[0] if args else kwargs.get("url", "")
        if "qksd-9k7j" in url:
            raise RuntimeError("simulated 500")
        return _mock_response(short)

    session = MagicMock()
    session.get.side_effect = side_effect
    adapter = MedicareAdvantageAdapter(root=REPO_ROOT, session=session)
    df = adapter.fetch(Query())
    # First resource raised; other two each returned 1 row.
    assert len(df) == 2


@pytest.mark.unit
def test_cms_socrata_url_uses_resource_base():
    assert SOCRATA_BASE == "https://data.cms.gov/resource"


# ---------------------------------------------------------------------------
# CKAN metastore (cms_open_payments, medicaid_fmap, chip)
# ---------------------------------------------------------------------------


def _metastore_payload(items: list[dict]) -> list[dict]:
    return items


def _ds_item(title: str, resource_id: str, dataset_id: str = "") -> dict:
    return {
        "title": title,
        "identifier": dataset_id or f"ds-{resource_id}",
        "distribution": [{"mediaType": "text/csv", "identifier": resource_id}],
    }


@pytest.mark.unit
@pytest.mark.parametrize(
    "adapter_cls,metastore_base,kw_match,kw_miss",
    [
        (
            CMSOpenPaymentsAdapter,
            "https://openpaymentsdata.cms.gov/api/1",
            "Open Payments General Payment 2024",
            "Random Other Dataset",
        ),
        (
            MedicaidFMAPAdapter,
            "https://data.medicaid.gov/api/1",
            "FMAP State Rates 2025",
            "Some Unrelated Dataset",
        ),
        (
            CHIPAdapter,
            "https://data.medicaid.gov/api/1",
            "CHIP Enrollment Summary",
            "Drug Spending Dashboard",
        ),
    ],
)
def test_ckan_metastore_keyword_filter_picks_matching_datasets(
    adapter_cls, metastore_base, kw_match, kw_miss
):
    session = MagicMock()
    items = [
        _ds_item(kw_miss, "no-match-001"),
        _ds_item(kw_match, "match-001"),
    ]
    session.get.return_value = _mock_response(_metastore_payload(items))
    session.post.return_value = _mock_response({"results": [{"state": "PR", "value": "1.0"}]})
    adapter = adapter_cls(root=REPO_ROOT, session=session)
    df = adapter.fetch(Query())
    # Metastore URL contains the configured base.
    metastore_call = session.get.call_args
    metastore_url = metastore_call.args[0] if metastore_call.args else metastore_call[0][0]
    assert metastore_base in metastore_url
    assert "/metastore/schemas/dataset/items" in metastore_url
    # POST hit the matched resource_id (not the missed one).
    post_url = session.post.call_args.args[0] if session.post.call_args.args else session.post.call_args[0][0]
    assert "match-001" in post_url
    assert "no-match-001" not in post_url
    assert len(df) == 1
    assert df.iloc[0]["source_resource_id"] == "match-001"


@pytest.mark.unit
def test_ckan_metastore_empty_metastore_returns_empty_df():
    session = MagicMock()
    session.get.return_value = _mock_response([])
    adapter = CMSOpenPaymentsAdapter(root=REPO_ROOT, session=session)
    df = adapter.fetch(Query())
    assert df.empty
    session.post.assert_not_called()


@pytest.mark.unit
def test_ckan_metastore_post_conditions_pin_state_field():
    session = MagicMock()
    session.get.return_value = _mock_response([_ds_item("Open Payments General", "resA")])
    session.post.return_value = _mock_response({"results": []})
    adapter = CMSOpenPaymentsAdapter(root=REPO_ROOT, session=session)
    adapter.fetch(Query())
    payload = session.post.call_args.kwargs.get("json") or session.post.call_args[1]["json"]
    fields = {c["property"] for c in payload["conditions"]}
    values = {c["value"] for c in payload["conditions"]}
    assert fields == {CMSOpenPaymentsAdapter.pr_filter_field}
    assert "PR" in values
    assert "Puerto Rico" in values


@pytest.mark.unit
def test_ckan_metastore_paginates_until_short_page():
    full = [{"state": "PR"} for _ in range(10000)]
    short = [{"state": "PR"}]
    session = MagicMock()
    session.get.return_value = _mock_response([_ds_item("FMAP State", "resA")])
    session.post.side_effect = [
        _mock_response({"results": full}),
        _mock_response({"results": short}),
    ]
    adapter = MedicaidFMAPAdapter(root=REPO_ROOT, session=session)
    df = adapter.fetch(Query())
    assert len(df) == 10001
    offsets = [
        (c.kwargs.get("json") or c[1]["json"])["offset"]
        for c in session.post.call_args_list
    ]
    assert offsets == [0, 10000]


@pytest.mark.unit
def test_ckan_metastore_metastore_down_returns_empty_df_not_crash():
    session = MagicMock()
    session.get.side_effect = RuntimeError("metastore 503")
    adapter = CHIPAdapter(root=REPO_ROOT, session=session)
    df = adapter.fetch(Query())
    assert df.empty


@pytest.mark.unit
def test_ckan_metastore_subclasses_have_distinct_base_urls():
    """OpenPayments and Medicaid hit different hosts even though they share the base class."""
    assert CMSOpenPaymentsAdapter.metastore_base.startswith("https://openpaymentsdata.cms.gov")
    assert MedicaidFMAPAdapter.metastore_base.startswith("https://data.medicaid.gov")
    assert CHIPAdapter.metastore_base.startswith("https://data.medicaid.gov")


@pytest.mark.unit
def test_ckan_metastore_keyword_match_is_case_insensitive():
    adapter = CMSOpenPaymentsAdapter(root=REPO_ROOT)
    assert adapter._matches_keyword("Open Payments Quarterly Report")
    assert adapter._matches_keyword("OPEN PAYMENTS QUARTERLY REPORT")
    assert adapter._matches_keyword("open payments quarterly report")
    assert not adapter._matches_keyword("Some other dataset")


@pytest.mark.unit
def test_ckan_metastore_tags_rows_with_source_dataset_id():
    session = MagicMock()
    session.get.return_value = _mock_response([_ds_item("CHIP State", "resA", dataset_id="ds-chip-2024")])
    session.post.return_value = _mock_response({"results": [{"state": "PR", "enrollment": 100}]})
    adapter = CHIPAdapter(root=REPO_ROOT, session=session)
    df = adapter.fetch(Query())
    assert len(df) == 1
    assert df.iloc[0]["source_dataset_id"] == "ds-chip-2024"
    assert df.iloc[0]["source_resource_id"] == "resA"
