"""Lobbying Disclosure Act (LDA) filings adapter.

Endpoint and request shape mirror the existing bulk producer at
`scripts/download_lda.py:_fetch_pass`. Two passes are made — one filtering
by `client_state="PR"` and one by `registrant_state="PR"` — and results
are deduped by `filing_uuid`. LDA filings carry no county/municipality
FIPS, so geographic narrowing happens client-side via the dispatcher's
`apply_post_ingest` call.

The LDA API works without authentication but is heavily rate-limited.
When the `LDA_API_KEY` env var is set, the adapter sends it as a
`Authorization: Token <key>` header (matches the producer pattern).
"""

from __future__ import annotations

import os
from typing import Any

import pandas as pd

from contract_sweeper.runtime.pagination_runtime import PageResult, paginate
from contract_sweeper.runtime.retry_runtime import RetryPolicy, with_retry

from ..types import Query
from .base import SourceAdapter

LDA_BASE = "https://lda.senate.gov/api/v1"
LDA_FILINGS_URL = f"{LDA_BASE}/filings/"
ENV_VAR = "LDA_API_KEY"
PAGE_SIZE = 100
MAX_PAGES = 200


def build_params(query: Query, *, state_param: str, page: int) -> dict[str, Any]:
    params: dict[str, Any] = {
        state_param: "PR",
        "page_size": PAGE_SIZE,
        "page": page,
    }
    if query.fiscal_years:
        # Multiple years → multiple values; the LDA API accepts repeated
        # filing_year params, but requests param dicts only carry the
        # last value, so we pass the most recent year (the producer takes
        # the same shortcut). Callers needing precise year sets can
        # narrow with date_range or run a per-year query.
        params["filing_year"] = max(int(y) for y in query.fiscal_years)
    return params


class LDAAdapter(SourceAdapter):
    source_id = "lda"

    def __init__(self, *, root, session=None, api_key: str | None = None):
        super().__init__(root=root)
        self._session = session
        self._api_key = api_key

    def _get_session(self):
        if self._session is not None:
            return self._session
        import requests

        key = self._api_key or os.environ.get(ENV_VAR, "").strip()
        s = requests.Session()
        headers = {
            "Accept": "application/json",
            "User-Agent": "contract-sweeper-query/1",
        }
        if key:
            headers["Authorization"] = f"Token {key}"
        s.headers.update(headers)
        return s

    def _get(self, session, params):
        resp = session.get(LDA_FILINGS_URL, params=params, timeout=60)
        resp.raise_for_status()
        return resp.json()

    def _fetch_pass(self, query: Query, *, state_param: str) -> list[dict]:
        session = self._get_session()
        policy = RetryPolicy(max_attempts=4, base_delay_seconds=1.0, max_delay_seconds=15.0)

        def fetch_page(marker):
            page = int(marker) if marker else 1
            params = build_params(query, state_param=state_param, page=page)
            data = with_retry(lambda: self._get(session, params), policy=policy)
            results = data.get("results", []) or []
            next_url = data.get("next")
            return PageResult(records=results, next_marker=(page + 1) if next_url else None)

        return list(paginate(fetch_page, start_marker=1, max_pages=MAX_PAGES))

    def fetch(self, query: Query) -> pd.DataFrame:
        seen: set[str] = set()
        rows: list[dict] = []
        for state_param in ("client_state", "registrant_state"):
            for rec in self._fetch_pass(query, state_param=state_param):
                uuid = (rec or {}).get("filing_uuid", "")
                if uuid and uuid in seen:
                    continue
                if uuid:
                    seen.add(uuid)
                rows.append(rec)
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(rows)
