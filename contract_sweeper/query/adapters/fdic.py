"""FDIC adapter — institution registry filtered to PR.

Wraps ``https://banks.data.fdic.gov/api/institutions`` matching the
existing bulk producer at ``scripts/download_fdic.py``. The endpoint
filters on ``STALP`` (state alpha code), not ``STATE`` — see the
producer's ``_download_institutions`` helper.

No credentials required.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from contract_sweeper.runtime.pagination_runtime import PageResult, paginate
from contract_sweeper.runtime.retry_runtime import RetryPolicy, with_retry

from ..types import Query
from .base import SourceAdapter

FDIC_BASE = "https://banks.data.fdic.gov/api"
FDIC_INSTITUTIONS_URL = f"{FDIC_BASE}/institutions"
PAGE_SIZE = 1000
MAX_PAGES = 50


class FDICInstitutionsAdapter(SourceAdapter):
    source_id = "fdic"

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

    def _get(self, session, params: dict[str, Any]):
        resp = session.get(FDIC_INSTITUTIONS_URL, params=params, timeout=60)
        resp.raise_for_status()
        return resp.json()

    def fetch(self, query: Query) -> pd.DataFrame:
        session = self._get_session()
        policy = RetryPolicy(max_attempts=4, base_delay_seconds=1.0, max_delay_seconds=15.0)

        def fetch_page(marker):
            offset = int(marker) if marker else 0
            params = {
                "filters": "STALP:PR",
                "limit": PAGE_SIZE,
                "offset": offset,
                "format": "json",
            }
            data = with_retry(lambda: self._get(session, params), policy=policy)
            data_block = data.get("data") or []
            records = [item.get("data", item) for item in data_block]
            total = (data.get("meta") or {}).get("total")
            next_offset = offset + PAGE_SIZE
            has_more = bool(records) and (total is None or next_offset < int(total))
            return PageResult(records=records, next_marker=next_offset if has_more else None)

        rows = list(paginate(fetch_page, start_marker=0, max_pages=MAX_PAGES))
        return pd.DataFrame(rows) if rows else pd.DataFrame()
