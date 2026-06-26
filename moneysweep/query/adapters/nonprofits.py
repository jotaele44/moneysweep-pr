"""ProPublica Nonprofit Explorer adapter (IRS 990 filings).

Wraps ``https://projects.propublica.org/nonprofits/api/v2`` matching
the existing bulk producer at ``scripts/download_nonprofits.py``:
phase-1 search by ``state[id]=PR`` with 0-indexed pagination.

Adds an optional ``PROPUBLICA_API_KEY`` header when set, mirroring the
producer's unauthenticated default with an upgrade path for higher rate
limits.
"""

from __future__ import annotations

import os
from typing import Any

import pandas as pd

from moneysweep.runtime.pagination_runtime import PageResult, paginate
from moneysweep.runtime.retry_runtime import RetryPolicy, with_retry

from ..types import Query
from .base import SourceAdapter

PROPUBLICA_BASE = "https://projects.propublica.org/nonprofits/api/v2"
SEARCH_URL = f"{PROPUBLICA_BASE}/organizations/search.json"
MAX_PAGES = 200


class NonprofitsIRS990Adapter(SourceAdapter):
    source_id = "nonprofits_irs990"

    def __init__(self, *, root, session=None):
        super().__init__(root=root)
        self._session = session

    def _get_session(self):
        if self._session is not None:
            return self._session
        import requests

        s = requests.Session()
        s.headers.update(
            {
                "Accept": "application/json",
                "User-Agent": "moneysweep-pr-query/1",
            }
        )
        api_key = os.environ.get("PROPUBLICA_API_KEY")
        if api_key:
            s.headers["X-API-Key"] = api_key
        return s

    def _get(self, session, params: dict[str, Any]):
        resp = session.get(SEARCH_URL, params=params, timeout=60)
        resp.raise_for_status()
        return resp.json()

    def fetch(self, query: Query) -> pd.DataFrame:
        session = self._get_session()
        policy = RetryPolicy(max_attempts=4, base_delay_seconds=1.0, max_delay_seconds=15.0)

        def fetch_page(marker):
            page = int(marker) if marker is not None else 0
            params = {"state[id]": "PR", "page": page}
            data = with_retry(lambda: self._get(session, params), policy=policy)
            records = data.get("organizations") or []
            return PageResult(
                records=records,
                next_marker=(page + 1) if records else None,
            )

        rows = list(paginate(fetch_page, start_marker=0, max_pages=MAX_PAGES))
        return pd.DataFrame(rows) if rows else pd.DataFrame()
