"""SBA adapters (CKAN datastore_search at data.sba.gov).

Wraps the SBA CKAN portal matching the existing bulk producer at
``scripts/download_sba.py``. CKAN ``resource_id`` values aren't stable
across re-publishes, so the adapter discovers the right resource by
searching ``package_search`` for keywords first and then paginating the
selected resource via ``datastore_search`` with ``filters={"State": "PR"}``.

Two concrete adapters share the same base:

* :class:`SBALoansAdapter` searches for the disaster-loan package.
* :class:`SBAPaycheckProtectionAdapter` searches for the PPP package.

If discovery fails (the package has been retired or renamed), the
adapter returns an empty DataFrame rather than raising.
"""

from __future__ import annotations

import json
from typing import Any

import pandas as pd

from moneysweep.runtime.pagination_runtime import PageResult, paginate
from moneysweep.runtime.retry_runtime import RetryPolicy, with_retry

from ..types import Query
from .base import SourceAdapter

CKAN_BASE = "https://data.sba.gov/api/3/action"
CKAN_PACKAGE_URL = f"{CKAN_BASE}/package_show"
CKAN_SEARCH_URL = f"{CKAN_BASE}/package_search"
CKAN_DATASTORE_URL = f"{CKAN_BASE}/datastore_search"
PAGE_SIZE = 1000
MAX_PAGES = 200


class _SBACKANAdapter(SourceAdapter):
    """Base class for SBA CKAN-backed adapters."""

    #: Candidate CKAN package IDs to try in order.
    package_ids: tuple[str, ...] = ()
    #: Search query string used if every package_show attempt fails.
    search_query: str = ""
    #: Column name CKAN uses for the borrower's state.
    state_field: str = "State"

    def __init__(self, *, root, session=None):
        super().__init__(root=root)
        self._session = session

    def _get_session(self):
        if self._session is not None:
            return self._session
        import requests

        s = requests.Session()
        s.headers.update({"Accept": "application/json", "User-Agent": "moneysweep-pr-query/1"})
        return s

    def _get(self, session, url: str, params: dict[str, Any]):
        resp = session.get(url, params=params, timeout=60)
        resp.raise_for_status()
        return resp.json()

    def _pick_csv_resource(self, resources: list[dict]) -> str | None:
        csv_resources = [r for r in resources if (r.get("format") or "").upper() == "CSV"]
        for r in csv_resources or resources:
            if r.get("id"):
                return r["id"]
        return None

    def _discover_resource_id(self, session, policy) -> str | None:
        for pkg_id in self.package_ids:
            data = with_retry(
                lambda: self._get(session, CKAN_PACKAGE_URL, {"id": pkg_id}),
                policy=policy,
            )
            if data and data.get("success"):
                rid = self._pick_csv_resource(data.get("result", {}).get("resources", []))
                if rid:
                    return rid
        if self.search_query:
            data = with_retry(
                lambda: self._get(session, CKAN_SEARCH_URL, {"q": self.search_query, "rows": 10}),
                policy=policy,
            )
            if data and data.get("success"):
                for pkg in data.get("result", {}).get("results", []):
                    rid = self._pick_csv_resource(pkg.get("resources", []))
                    if rid:
                        return rid
        return None

    def fetch(self, query: Query) -> pd.DataFrame:
        session = self._get_session()
        policy = RetryPolicy(max_attempts=4, base_delay_seconds=1.0, max_delay_seconds=15.0)

        try:
            resource_id = self._discover_resource_id(session, policy)
        except Exception:
            return pd.DataFrame()
        if not resource_id:
            return pd.DataFrame()

        filters = json.dumps({self.state_field: "PR"})

        def fetch_page(marker):
            offset = int(marker) if marker else 0
            params = {
                "resource_id": resource_id,
                "filters": filters,
                "limit": PAGE_SIZE,
                "offset": offset,
            }
            data = with_retry(
                lambda: self._get(session, CKAN_DATASTORE_URL, params),
                policy=policy,
            )
            if not data or not data.get("success"):
                return PageResult(records=[], next_marker=None)
            records = (data.get("result") or {}).get("records") or []
            next_offset = offset + PAGE_SIZE
            has_more = bool(records) and len(records) == PAGE_SIZE
            return PageResult(records=records, next_marker=next_offset if has_more else None)

        rows = list(paginate(fetch_page, start_marker=0, max_pages=MAX_PAGES))
        return pd.DataFrame(rows) if rows else pd.DataFrame()


class SBALoansAdapter(_SBACKANAdapter):
    """SBA disaster loan dataset (7(a) / 504 + disaster) via data.sba.gov."""

    source_id = "sba_loans"
    package_ids = (
        "disaster-loan-data",
        "sba-disaster-loan-data",
        "disaster-loans",
        "sba-disaster-loans",
        "fema-disaster-loans",
    )
    search_query = "disaster loan"


class SBAPaycheckProtectionAdapter(_SBACKANAdapter):
    """SBA Paycheck Protection Program (PPP) dataset via data.sba.gov."""

    source_id = "sba_ppp"
    package_ids = (
        "ppp-foia",
        "paycheck-protection-program-loans",
        "ppp-loan-data",
    )
    search_query = "paycheck protection"
    state_field = "BorrowerState"
