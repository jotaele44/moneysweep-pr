"""SBIR / STTR awards adapter.

Endpoint and pagination pattern mirror the existing bulk producer at
`scripts/download_sbir.py:_paginate` — GETs `api.sbir.gov/public/awards`
with `state=PR` and `start` / `rows` pagination. Falls back to the
www.sbir.gov search endpoint when the api.sbir.gov endpoint is unavailable
(matches the producer's failover behavior).

SBIR responses don't carry a county FIPS; municipality narrowing is
applied client-side via `apply_post_ingest` in the dispatcher.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from contract_sweeper.runtime.pagination_runtime import PageResult, paginate
from contract_sweeper.runtime.retry_runtime import RetryPolicy, with_retry

from ..types import Query
from .base import SourceAdapter

SBIR_API_URL = "https://api.sbir.gov/public/awards"
SBIR_SEARCH_URL = "https://www.sbir.gov/api/awards.json"
PAGE_SIZE = 100
MAX_PAGES = 100


# (base_url, count_field, data_field, start_param, size_param, state_param)
ENDPOINTS = [
    (SBIR_API_URL, "totalCount", "data", "start", "rows", "state"),
    (SBIR_SEARCH_URL, "total", "results", "start", "count", "firm_state"),
]


def _records_from_response(data: Any, data_field: str) -> list[dict]:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return data.get(data_field, []) or data.get("awards", []) or []
    return []


def _total_from_response(data: Any, count_field: str) -> int | None:
    if isinstance(data, list):
        return len(data)
    if isinstance(data, dict):
        v = data.get(count_field) or data.get("total")
        if v is None:
            return None
        try:
            return int(v)
        except (TypeError, ValueError):
            return None
    return None


class SBIRAdapter(SourceAdapter):
    source_id = "sbir"

    def __init__(self, *, root, session=None):
        super().__init__(root=root)
        self._session = session

    def _get_session(self):
        if self._session is not None:
            return self._session
        import requests

        s = requests.Session()
        s.headers.update({"Accept": "application/json", "User-Agent": "contract-sweeper-query/1"})
        return s

    def _get(self, session, url, params):
        resp = session.get(url, params=params, timeout=60)
        resp.raise_for_status()
        return resp.json()

    def fetch(self, query: Query) -> pd.DataFrame:
        session = self._get_session()
        policy = RetryPolicy(max_attempts=4, base_delay_seconds=1.0, max_delay_seconds=15.0)

        for base_url, count_field, data_field, start_param, size_param, state_param in ENDPOINTS:
            params = {state_param: "PR", size_param: PAGE_SIZE, start_param: 0}
            if query.fiscal_years:
                # Some endpoints accept year filters; harmless if ignored.
                params["year"] = sorted({int(y) for y in query.fiscal_years})

            def fetch_page(
                marker,
                _params=params,
                _base=base_url,
                _start=start_param,
                _data=data_field,
                _count=count_field,
            ):
                start = int(marker) if marker else 0
                page_params = dict(_params)
                page_params[_start] = start
                data = with_retry(lambda: self._get(session, _base, page_params), policy=policy)
                records = _records_from_response(data, _data)
                total = _total_from_response(data, _count)
                next_marker = (
                    (start + PAGE_SIZE)
                    if records and (total is None or start + PAGE_SIZE < total)
                    else None
                )
                return PageResult(records=records, next_marker=next_marker)

            try:
                rows = list(paginate(fetch_page, start_marker=0, max_pages=MAX_PAGES))
            except Exception:  # noqa: BLE001 — try the fallback endpoint
                continue
            if rows:
                return pd.DataFrame(rows)
        return pd.DataFrame()
