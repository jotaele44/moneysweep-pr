"""OpenFEMA Public Assistance Funded Projects (v2) adapter.

Endpoint and filter shape mirror the existing bulk producer at
`scripts/download_openfema_pa_projects.py`. Adds a `countyFips` clause
when the caller passes specific municipalities.
"""
from __future__ import annotations

from typing import Any

import pandas as pd

from contract_sweeper.runtime.geo_attribution import _load_reference, _normalize_pr_name
from contract_sweeper.runtime.pagination_runtime import PageResult, paginate
from contract_sweeper.runtime.retry_runtime import RetryPolicy, with_retry

from ..types import Query
from .base import SourceAdapter

OPENFEMA_URL = (
    "https://www.fema.gov/api/open/v2/PublicAssistanceFundedProjectsDetails"
)
PAGE_SIZE = 1000
MAX_PAGES = 200


def _municipalities_to_fips(municipalities: tuple[str, ...], root) -> list[str]:
    """Translate canonical names or FIPS codes → 5-digit PR county FIPS."""
    ref = _load_reference(str(root))
    by_fips = ref["by_fips"]
    by_alias = ref["by_alias"]
    out: set[str] = set()
    for m in municipalities:
        if not m:
            continue
        s = str(m).strip()
        if s.isdigit():
            padded = s.zfill(5)
            if padded in by_fips:
                out.add(padded)
            continue
        rec = by_alias.get(_normalize_pr_name(s))
        if rec is not None:
            out.add(rec["geo_municipality_code"])
    return sorted(out)


def build_filter(query: Query, *, root) -> str:
    parts: list[str] = ["state eq 'PR'"]
    fips = _municipalities_to_fips(query.municipalities, root)
    if fips:
        clause = " or ".join(f"countyFips eq '{c}'" for c in fips)
        parts.append(f"({clause})")
    if query.fiscal_years:
        years = sorted({int(y) for y in query.fiscal_years})
        clause = " or ".join(f"declarationFY eq {y}" for y in years)
        parts.append(f"({clause})")
    return " and ".join(parts)


class OpenFEMAPaAdapter(SourceAdapter):
    source_id = "fema_pa_openfema_v2"

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
        resp = session.get(OPENFEMA_URL, params=params, timeout=60)
        resp.raise_for_status()
        return resp.json()

    def fetch(self, query: Query) -> pd.DataFrame:
        session = self._get_session()
        policy = RetryPolicy(max_attempts=4, base_delay_seconds=1.0, max_delay_seconds=15.0)
        filt = build_filter(query, root=self.root)

        def fetch_page(marker):
            skip = int(marker) if marker else 0
            params = {"$filter": filt, "$top": PAGE_SIZE, "$skip": skip, "$format": "json"}
            data = with_retry(lambda: self._get(session, params), policy=policy)
            records = data.get("PublicAssistanceFundedProjectsDetails", []) or []
            has_more = len(records) == PAGE_SIZE
            return PageResult(records=records, next_marker=(skip + PAGE_SIZE) if has_more else None)

        rows = list(paginate(fetch_page, start_marker=0, max_pages=MAX_PAGES))
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(rows)
