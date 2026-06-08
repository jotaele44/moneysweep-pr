"""FEC Open API adapter (Schedule A contributions, PR state filter).

Auth pattern matches `scripts/download_fec.py`: `X-Api-Key` header sourced
from the `FEC_API_KEY` env var. The Schedule A endpoint doesn't accept a
PR municipality / county FIPS filter, so municipality narrowing is handled
client-side via `apply_post_ingest` in the dispatcher.
"""

from __future__ import annotations

import os
from typing import Any

import pandas as pd

from contract_sweeper.runtime.pagination_runtime import PageResult, paginate
from contract_sweeper.runtime.retry_runtime import RetryPolicy, with_retry

from ..types import CredentialMissing, Query
from .base import SourceAdapter

FEC_BASE = "https://api.open.fec.gov/v1"
SCHED_A_URL = f"{FEC_BASE}/schedules/schedule_a/"
ENV_VAR = "FEC_API_KEY"
PAGE_SIZE = 100
MAX_PAGES = 100


class FECPRAdapter(SourceAdapter):
    source_id = "fec"

    def __init__(self, *, root, session=None, api_key: str | None = None):
        super().__init__(root=root)
        self._session = session
        self._api_key = api_key

    def _resolved_api_key(self) -> str:
        key = self._api_key or os.environ.get(ENV_VAR, "").strip()
        if not key:
            raise CredentialMissing(self.source_id, ENV_VAR)
        return key

    def _get_session(self, api_key: str):
        if self._session is not None:
            return self._session
        import requests

        s = requests.Session()
        s.headers.update(
            {
                "X-Api-Key": api_key,
                "Accept": "application/json",
                "User-Agent": "contract-sweeper-query/1",
            }
        )
        return s

    def _get(self, session, params: dict[str, Any]):
        resp = session.get(SCHED_A_URL, params=params, timeout=60)
        resp.raise_for_status()
        return resp.json()

    def fetch(self, query: Query) -> pd.DataFrame:
        api_key = self._resolved_api_key()
        session = self._get_session(api_key)
        policy = RetryPolicy(max_attempts=4, base_delay_seconds=1.0, max_delay_seconds=15.0)

        base_params: dict[str, Any] = {
            "contributor_state": "PR",
            "per_page": PAGE_SIZE,
            "sort": "-contribution_receipt_date",
        }
        if query.fiscal_years:
            base_params["two_year_transaction_period"] = sorted(
                {int(y) for y in query.fiscal_years}
            )
        if query.date_range:
            base_params["min_date"], base_params["max_date"] = query.date_range

        def fetch_page(marker):
            params = dict(base_params)
            if marker:
                # FEC uses last_indexes for cursor pagination; the simplest form
                # is page-style and is supported on schedule_a.
                params["page"] = marker
            data = with_retry(lambda: self._get(session, params), policy=policy)
            results = data.get("results", []) or []
            pagination = data.get("pagination", {}) or {}
            page = int(pagination.get("page", 1))
            pages = int(pagination.get("pages", 1))
            next_marker = (page + 1) if page < pages else None
            return PageResult(records=results, next_marker=next_marker)

        rows = list(paginate(fetch_page, start_marker=1, max_pages=MAX_PAGES))
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(rows)
