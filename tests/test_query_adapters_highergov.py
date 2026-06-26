"""Tests for the HigherGov supplemental query adapter (mocked HTTP).

Wave G, PR 7. Of the adapters slated for this pass — sam, ofac, cms_socrata,
ckan_metastore, highergov — the first four already have credential/error-path
coverage (tests/test_query_entity_adapters.py, tests/test_query_adapters_cms.py).
HigherGov was the remaining gap, so it is covered here: the credential gate, the
pagination/extraction happy paths, and the payload-shape tolerance of
``_extract_records``. No real HTTP — sessions are injected MagicMocks.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from moneysweep.query.adapters.highergov import (
    ENV_VAR,
    HigherGovSupplementalAdapter,
)
from moneysweep.query.types import CredentialMissing, Query

REPO_ROOT = Path(__file__).resolve().parents[1]


def _mock_response(payload):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = payload
    resp.raise_for_status = MagicMock()
    return resp


# --------------------------------------------------------------------------- #
# Credential gate
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_raises_credential_missing_before_any_http(monkeypatch):
    monkeypatch.delenv(ENV_VAR, raising=False)
    session = MagicMock()
    adapter = HigherGovSupplementalAdapter(root=REPO_ROOT, session=session)
    with pytest.raises(CredentialMissing) as exc:
        adapter.fetch(Query())
    # The error names the source and the missing env var, and no call was made.
    assert ENV_VAR in str(exc.value)
    session.get.assert_not_called()


@pytest.mark.unit
def test_constructor_api_key_satisfies_credential_gate(monkeypatch):
    monkeypatch.delenv(ENV_VAR, raising=False)
    session = MagicMock()
    session.get.return_value = _mock_response({"results": []})
    adapter = HigherGovSupplementalAdapter(root=REPO_ROOT, session=session, api_key="ctor-key")
    adapter.fetch(Query())  # must not raise
    params = session.get.call_args.kwargs["params"]
    assert params["api_key"] == "ctor-key"


@pytest.mark.unit
def test_env_var_api_key_is_used_when_constructor_key_absent(monkeypatch):
    monkeypatch.setenv(ENV_VAR, "env-key")
    session = MagicMock()
    session.get.return_value = _mock_response({"results": []})
    adapter = HigherGovSupplementalAdapter(root=REPO_ROOT, session=session)
    adapter.fetch(Query())
    assert session.get.call_args.kwargs["params"]["api_key"] == "env-key"


# --------------------------------------------------------------------------- #
# Request shape
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_request_targets_resource_endpoint_with_search_id(monkeypatch):
    monkeypatch.setenv(ENV_VAR, "k")
    session = MagicMock()
    session.get.return_value = _mock_response({"results": []})
    adapter = HigherGovSupplementalAdapter(root=REPO_ROOT, session=session)
    adapter.fetch(Query())

    call = session.get.call_args
    url = call.args[0] if call.args else call.kwargs["url"]
    assert url == "https://highergov.com/api-external/contract/"
    params = call.kwargs["params"]
    assert params["search_id"] == HigherGovSupplementalAdapter.search_id
    assert params["page"] == 1
    assert params["page_size"] == 2000


# --------------------------------------------------------------------------- #
# _extract_records — payload-shape tolerance
# --------------------------------------------------------------------------- #


@pytest.mark.unit
@pytest.mark.parametrize(
    "payload,expected",
    [
        ([{"a": 1}], [{"a": 1}]),  # bare list
        ({"results": [{"a": 1}]}, [{"a": 1}]),  # canonical envelope key
        ({"data": [{"b": 2}]}, [{"b": 2}]),
        ({"items": [{"c": 3}]}, [{"c": 3}]),
        ({"rows": [{"d": 4}]}, [{"d": 4}]),
        ({"hits": [{"e": 5}]}, [{"e": 5}]),
        ({"unknown_key": [{"f": 6}]}, [{"f": 6}]),  # first list value fallback
        ({"count": 0, "results": []}, []),  # empty list
        ({"no": "lists", "here": 1}, []),  # nothing list-shaped
        ("not-a-container", []),
    ],
)
def test_extract_records_handles_varied_payloads(payload, expected):
    assert HigherGovSupplementalAdapter._extract_records(payload) == expected


# --------------------------------------------------------------------------- #
# fetch — extraction + pagination
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_fetch_returns_empty_dataframe_when_no_records(monkeypatch):
    monkeypatch.setenv(ENV_VAR, "k")
    session = MagicMock()
    session.get.return_value = _mock_response({"results": []})
    adapter = HigherGovSupplementalAdapter(root=REPO_ROOT, session=session)
    df = adapter.fetch(Query())
    assert df.empty


@pytest.mark.unit
def test_fetch_single_short_page_returns_rows(monkeypatch):
    monkeypatch.setenv(ENV_VAR, "k")
    rows = [{"id": "C1", "agency": "DOD"}, {"id": "C2", "agency": "HHS"}]
    session = MagicMock()
    session.get.return_value = _mock_response({"results": rows})
    adapter = HigherGovSupplementalAdapter(root=REPO_ROOT, session=session)
    df = adapter.fetch(Query())
    assert len(df) == 2
    assert set(df["id"]) == {"C1", "C2"}
    # A short first page terminates pagination after one request.
    assert session.get.call_count == 1


@pytest.mark.unit
def test_fetch_paginates_until_short_page(monkeypatch):
    monkeypatch.setenv(ENV_VAR, "k")
    # Shrink the page size so two small pages exercise the pagination loop.
    monkeypatch.setattr("moneysweep.query.adapters.highergov.PAGE_SIZE", 2)
    full_page = [{"id": "A"}, {"id": "B"}]  # len == PAGE_SIZE -> has_more
    short_page = [{"id": "C"}]  # len < PAGE_SIZE -> stop
    session = MagicMock()
    session.get.side_effect = [
        _mock_response({"results": full_page}),
        _mock_response({"results": short_page}),
    ]
    adapter = HigherGovSupplementalAdapter(root=REPO_ROOT, session=session)
    df = adapter.fetch(Query())
    assert len(df) == 3
    assert session.get.call_count == 2
    # Second request advanced to page 2.
    assert session.get.call_args_list[1].kwargs["params"]["page"] == 2
