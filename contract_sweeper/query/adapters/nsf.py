"""NSF awards adapter.

Endpoint and request shape mirror the existing bulk producer at
`scripts/download_research.py` (NSF half — NIH is in `nih.py`). GETs
`api.nsf.gov/services/v1/awards.json` with `awardeeStateCode="PR"` and
page-style pagination via the `offset` parameter.

NSF awards carry a `awardeeCity` and `awardeeStateCode` but no county
FIPS, so municipality narrowing happens client-side via the dispatcher's
`apply_post_ingest` call. The registry's source_id for NSF awards is
`research_grants`.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from contract_sweeper.runtime.pagination_runtime import PageResult, paginate
from contract_sweeper.runtime.retry_runtime import RetryPolicy, with_retry

from ..types import Query
from .base import SourceAdapter

NSF_API_URL = "https://api.nsf.gov/services/v1/awards.json"
PAGE_SIZE = 25  # NSF API default; max 25 per page
MAX_PAGES = 400

PRINT_FIELDS = (
    "id,agency,awardeeName,awardeeCity,awardeeStateCode,awardeeZipCode,"
    "title,fundsObligatedAmt,date,startDate,expDate,"
    "piFirstName,piLastName,abstractText"
)


def build_params(query: Query, *, offset: int) -> dict[str, Any]:
    params: dict[str, Any] = {
        "awardeeStateCode": "PR",
        "printFields": PRINT_FIELDS,
        "offset": offset,
        "rpp": PAGE_SIZE,
    }
    if query.fiscal_years:
        # NSF supports `dateStart`/`dateEnd` MM/DD/YYYY filters.
        years = sorted({int(y) for y in query.fiscal_years})
        params["dateStart"] = f"01/01/{years[0]}"
        params["dateEnd"] = f"12/31/{years[-1]}"
    if query.agencies:
        params["agency"] = query.agencies[0]
    return params


class NSFAwardsAdapter(SourceAdapter):
    source_id = "research_grants"

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

    def _get(self, session, params):
        resp = session.get(NSF_API_URL, params=params, timeout=60)
        resp.raise_for_status()
        return resp.json()

    def fetch(self, query: Query) -> pd.DataFrame:
        session = self._get_session()
        policy = RetryPolicy(max_attempts=4, base_delay_seconds=1.0, max_delay_seconds=15.0)

        def fetch_page(marker):
            offset = int(marker) if marker else 1  # NSF offsets are 1-indexed
            params = build_params(query, offset=offset)
            data = with_retry(lambda: self._get(session, params), policy=policy)
            response = data.get("response", {}) or {}
            records = response.get("award", []) or []
            # NSF API doesn't return a total; we stop when a page comes back short.
            has_more = len(records) == PAGE_SIZE
            return PageResult(
                records=records, next_marker=(offset + PAGE_SIZE) if has_more else None
            )

        rows = list(paginate(fetch_page, start_marker=1, max_pages=MAX_PAGES))
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(rows)
