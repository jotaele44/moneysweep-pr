"""OpenCorporates adapter — PR company registry (jurisdiction `us_pr`).

Wraps ``https://api.opencorporates.com/v0.4/companies/search`` matching
the existing bulk producer at ``scripts/download_opencorporates.py``.

``OPENCORPORATES_API_TOKEN`` is **optional** — the API works without it
at a lower rate limit. Unlike :class:`FECPRAdapter`, this adapter does
NOT raise :class:`CredentialMissing` when the token is unset.
"""

from __future__ import annotations

import os
from typing import Any

import pandas as pd

from contract_sweeper.runtime.pagination_runtime import PageResult, paginate
from contract_sweeper.runtime.retry_runtime import RetryPolicy, with_retry

from ..types import Query
from .base import SourceAdapter

OC_BASE = "https://api.opencorporates.com/v0.4"
SEARCH_URL = f"{OC_BASE}/companies/search"
JURISDICTION = "us_pr"
PER_PAGE = 100
MAX_PAGES = 200
ENV_VAR = "OPENCORPORATES_API_TOKEN"


class OpenCorporatesAdapter(SourceAdapter):
    source_id = "opencorporates"

    def __init__(self, *, root, session=None, api_token: str | None = None):
        super().__init__(root=root)
        self._session = session
        self._api_token = api_token

    def _resolved_api_token(self) -> str | None:
        token = self._api_token or os.environ.get(ENV_VAR, "").strip()
        return token or None

    def _get_session(self):
        if self._session is not None:
            return self._session
        import requests

        s = requests.Session()
        s.headers.update({"Accept": "application/json", "User-Agent": "contract-sweeper-query/1"})
        return s

    def _get(self, session, params: dict[str, Any]):
        resp = session.get(SEARCH_URL, params=params, timeout=60)
        resp.raise_for_status()
        return resp.json()

    def fetch(self, query: Query) -> pd.DataFrame:
        session = self._get_session()
        token = self._resolved_api_token()
        policy = RetryPolicy(max_attempts=4, base_delay_seconds=1.0, max_delay_seconds=15.0)

        def fetch_page(marker):
            page = int(marker) if marker else 1
            params: dict[str, Any] = {
                "jurisdiction_code": JURISDICTION,
                "per_page": PER_PAGE,
                "page": page,
            }
            if token:
                params["api_token"] = token
            data = with_retry(lambda: self._get(session, params), policy=policy)
            companies_block = (data.get("results") or {}).get("companies") or []
            records = [item.get("company", item) for item in companies_block]
            total_pages = int((data.get("results") or {}).get("total_pages", page))
            has_more = bool(records) and page < total_pages
            return PageResult(records=records, next_marker=(page + 1) if has_more else None)

        rows = list(paginate(fetch_page, start_marker=1, max_pages=MAX_PAGES))
        return pd.DataFrame(rows) if rows else pd.DataFrame()
