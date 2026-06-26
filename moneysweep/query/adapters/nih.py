"""NIH Reporter adapter.

Endpoint and request shape mirror the existing bulk producer at
`scripts/download_nih.py:_paginate` — POSTs to the v2 projects/search
endpoint with `criteria.org_state="PR"` and offset/limit pagination.

NIH Reporter does not accept county- or municipality-level filters for PR,
so the municipality narrowing in the caller's `Query` is applied
client-side via `apply_post_ingest` in the dispatcher.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from moneysweep.runtime.pagination_runtime import PageResult, paginate
from moneysweep.runtime.retry_runtime import RetryPolicy, with_retry

from ..types import Query
from .base import SourceAdapter

NIH_REPORTER_URL = "https://api.reporter.nih.gov/v2/projects/search"
PAGE_LIMIT = 500
MAX_PAGES = 200

NIH_INCLUDE_FIELDS = [
    "ProjectNum",
    "ProjectTitle",
    "OrgName",
    "OrgCity",
    "OrgState",
    "OrgZipcode",
    "ContactPiName",
    "FiscalYear",
    "AwardAmount",
    "TotalCost",
    "ProjectStartDate",
    "ProjectEndDate",
    "ActivityCode",
    "StudySection",
]


def _resolve_fiscal_years(query: Query) -> list[int]:
    if query.fiscal_years:
        return sorted({int(y) for y in query.fiscal_years})
    # Wide default consistent with the bulk producer.
    return list(range(2010, 2027))


def build_payload(query: Query, *, offset: int = 0) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "criteria": {
            "org_state": ["PR"],
            "fiscal_years": _resolve_fiscal_years(query),
        },
        "include_fields": NIH_INCLUDE_FIELDS,
        "offset": offset,
        "limit": PAGE_LIMIT,
        "sort_field": "TotalCost",
        "sort_order": "desc",
    }
    if query.agencies:
        payload["criteria"]["agencies"] = list(query.agencies)
    return payload


class NIHReporterAdapter(SourceAdapter):
    source_id = "nih_reporter"

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
                "Content-Type": "application/json",
                "User-Agent": "moneysweep-pr-query/1",
            }
        )
        return s

    def _post(self, session, payload):
        resp = session.post(NIH_REPORTER_URL, json=payload, timeout=60)
        resp.raise_for_status()
        return resp.json()

    def fetch(self, query: Query) -> pd.DataFrame:
        session = self._get_session()
        policy = RetryPolicy(max_attempts=4, base_delay_seconds=1.0, max_delay_seconds=15.0)

        def fetch_page(marker):
            offset = int(marker) if marker else 0
            data = with_retry(
                lambda: self._post(session, build_payload(query, offset=offset)),
                policy=policy,
            )
            results = data.get("results", []) or []
            total = int((data.get("meta", {}) or {}).get("total", 0))
            next_offset = offset + PAGE_LIMIT
            next_marker = next_offset if next_offset < total and results else None
            return PageResult(records=results, next_marker=next_marker)

        rows = list(paginate(fetch_page, start_marker=0, max_pages=MAX_PAGES))
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(rows)
