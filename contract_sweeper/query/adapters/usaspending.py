"""USAspending prime-award adapter.

Targets the public `spending_by_award` endpoint with a place-of-performance
filter that includes both the PR state code and (when the caller passes
municipalities) the 3-digit county FIPS suffix derived from the canonical
PR municipalities reference table.

Endpoint and request shape mirror the existing bulk producer at
`scripts/download_grants.py:_build_bulk_payload` and
`scripts/download_subawards.py:_fetch_page`.
"""
from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd

# `requests` is imported lazily inside fetch() so unit tests can run without it.
from contract_sweeper.runtime.geo_attribution import _load_reference
from contract_sweeper.runtime.pagination_runtime import PageResult, paginate
from contract_sweeper.runtime.retry_runtime import RetryPolicy, with_retry

from ..types import Query
from .base import SourceAdapter

USASPENDING_URL = "https://api.usaspending.gov/api/v2/search/spending_by_award/"
CONTRACT_TYPE_CODES = ["A", "B", "C", "D"]
PAGE_LIMIT = 100
MAX_PAGES = 200

PRIME_FIELDS = [
    "Award ID",
    "Recipient Name",
    "recipient_uei",
    "Awarding Agency",
    "Awarding Sub Agency",
    "Award Amount",
    "Start Date",
    "End Date",
    "Place of Performance State Code",
    "Place of Performance County Name",
    "Place of Performance City",
    "Description",
    "awarding_agency_id",
]


def _municipalities_to_county_suffixes(
    municipalities: tuple[str, ...], root
) -> list[str]:
    """Translate canonical names or FIPS codes → 3-digit PR county suffixes.

    USAspending's `place_of_performance_locations` filter wants the 3-digit
    county FIPS *without* the state prefix (`'127'`, not `'72127'`).
    """
    ref = _load_reference(str(root))
    by_fips = ref["by_fips"]
    by_alias = ref["by_alias"]
    suffixes: set[str] = set()
    for m in municipalities:
        if not m:
            continue
        s = str(m).strip()
        # FIPS form
        if s.isdigit():
            padded = s.zfill(5)
            if padded in by_fips:
                suffixes.add(padded[2:])
            continue
        # Name form — reuse the attributor's normalizer via the alias index.
        from contract_sweeper.runtime.geo_attribution import _normalize_pr_name

        key = _normalize_pr_name(s)
        rec = by_alias.get(key)
        if rec is not None:
            suffixes.add(rec["geo_municipality_code"][2:])
    return sorted(suffixes)


def _date_window(query: Query) -> tuple[str, str]:
    """Resolve query date_range or fiscal_years to (start_iso, end_iso)."""
    if query.date_range:
        return query.date_range[0], query.date_range[1]
    if query.fiscal_years:
        # US federal FY ends Sept 30. FY2024 → 2023-10-01 .. 2024-09-30.
        fys = sorted({int(y) for y in query.fiscal_years})
        start = f"{fys[0] - 1}-10-01"
        end = f"{fys[-1]}-09-30"
        return start, end
    # Wide default: last 25 federal FYs ending today.
    today = date.today()
    return f"{today.year - 25}-10-01", today.isoformat()


def build_payload(query: Query, *, root, page: int = 1) -> dict[str, Any]:
    counties = _municipalities_to_county_suffixes(query.municipalities, root)
    if counties:
        locations = [
            {"country": "USA", "state": "PR", "county": c} for c in counties
        ]
    else:
        locations = [{"country": "USA", "state": "PR"}]
    start, end = _date_window(query)
    filters: dict[str, Any] = {
        "award_type_codes": CONTRACT_TYPE_CODES,
        "time_period": [{"start_date": start, "end_date": end}],
        "place_of_performance_locations": locations,
    }
    if query.agencies:
        filters["agencies"] = [
            {"type": "awarding", "tier": "toptier", "name": a} for a in query.agencies
        ]
    if query.recipient_ueis:
        filters["recipient_search_text"] = list(query.recipient_ueis)
    return {
        "filters": filters,
        "fields": PRIME_FIELDS,
        "page": page,
        "limit": PAGE_LIMIT,
        "sort": "Award Amount",
        "order": "desc",
    }


class USAspendingPrimeAdapter(SourceAdapter):
    source_id = "usaspending_prime"

    def __init__(self, *, root, session=None):
        super().__init__(root=root)
        self._session = session  # Injectable for tests.

    def _get_session(self):
        if self._session is not None:
            return self._session
        import requests  # imported here so test envs without `requests` can still import the module

        s = requests.Session()
        s.headers.update({"Accept": "application/json", "User-Agent": "contract-sweeper-query/1"})
        return s

    def _post(self, session, payload):
        resp = session.post(USASPENDING_URL, json=payload, timeout=60)
        resp.raise_for_status()
        return resp.json()

    def fetch(self, query: Query) -> pd.DataFrame:
        session = self._get_session()
        policy = RetryPolicy(max_attempts=4, base_delay_seconds=1.0, max_delay_seconds=15.0)

        def fetch_page(marker):
            page = int(marker) if marker else 1
            data = with_retry(
                lambda: self._post(session, build_payload(query, root=self.root, page=page)),
                policy=policy,
            )
            records = data.get("results", []) or []
            meta = data.get("page_metadata", {}) or {}
            has_next = bool(meta.get("hasNext"))
            return PageResult(records=records, next_marker=(page + 1) if has_next else None)

        rows = list(paginate(fetch_page, start_marker=1, max_pages=MAX_PAGES))
        if not rows:
            return pd.DataFrame(columns=PRIME_FIELDS)
        return pd.DataFrame(rows)
