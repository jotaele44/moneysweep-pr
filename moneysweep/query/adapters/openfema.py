"""OpenFEMA adapters — Public Assistance and Hazard Mitigation (HMGP).

Endpoints and filter shapes mirror the existing bulk producer at
`scripts/download_openfema_pa_projects.py` and `scripts/download_fema.py`.
Adds a `countyFips` clause when the caller passes specific municipalities;
HMGP records don't carry county FIPS so that adapter narrows to PR state
only and lets `apply_post_ingest` do municipality-level enrichment.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from moneysweep.runtime.geo_attribution import _load_reference, _normalize_pr_name
from moneysweep.runtime.pagination_runtime import PageResult, paginate
from moneysweep.runtime.retry_runtime import RetryPolicy, with_retry

from ..types import Query
from .base import SourceAdapter

FEMA_BASE = "https://www.fema.gov/api/open/v2/"
OPENFEMA_PA_URL = FEMA_BASE + "PublicAssistanceFundedProjectsDetails"
OPENFEMA_HMGP_URL = FEMA_BASE + "HazardMitigationGrantProgramDisasterSummaries"
OPENFEMA_NFIP_URL = FEMA_BASE + "FimaNfipClaims"
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


def build_hmgp_filter(query: Query) -> str:
    """HMGP records carry stateCode but no countyFips; filter by state only.

    Caller-supplied municipalities are still useful — the dispatcher's
    post_ingest step attributes geo on the returned rows so callers can
    filter client-side.
    """
    parts: list[str] = ["stateCode eq 'PR'"]
    if query.fiscal_years:
        years = sorted({int(y) for y in query.fiscal_years})
        clause = " or ".join(
            f"projectAmount ne null and disasterNumber ne null and incidentDate ge '{y}-01-01' and incidentDate le '{y}-12-31'"
            for y in years
        )
        parts.append(f"({clause})")
    return " and ".join(parts)


class _OpenFEMABase(SourceAdapter):
    """Shared HTTP + pagination scaffolding for OpenFEMA v2 endpoints."""

    endpoint_url: str = ""
    data_key: str = ""

    def __init__(self, *, root, session=None):
        super().__init__(root=root)
        self._session = session

    def _get_session(self):
        if self._session is not None:
            return self._session
        import requests

        s = requests.Session()
        s.headers.update({"Accept": "application/json", "User-Agent": "moneysweep-pr-query/1"})
        return s

    def _get(self, session, params: dict[str, Any]):
        resp = session.get(self.endpoint_url, params=params, timeout=60)
        resp.raise_for_status()
        return resp.json()

    def _paginate(self, filt: str) -> list[dict]:
        session = self._get_session()
        policy = RetryPolicy(max_attempts=4, base_delay_seconds=1.0, max_delay_seconds=15.0)

        def fetch_page(marker):
            skip = int(marker) if marker else 0
            params = {"$filter": filt, "$top": PAGE_SIZE, "$skip": skip, "$format": "json"}
            data = with_retry(lambda: self._get(session, params), policy=policy)
            records = data.get(self.data_key, []) or []
            has_more = len(records) == PAGE_SIZE
            return PageResult(records=records, next_marker=(skip + PAGE_SIZE) if has_more else None)

        return list(paginate(fetch_page, start_marker=0, max_pages=MAX_PAGES))


class OpenFEMAPaAdapter(_OpenFEMABase):
    source_id = "fema_pa_openfema_v2"
    endpoint_url = OPENFEMA_PA_URL
    data_key = "PublicAssistanceFundedProjectsDetails"

    def fetch(self, query: Query) -> pd.DataFrame:
        rows = self._paginate(build_filter(query, root=self.root))
        return pd.DataFrame(rows) if rows else pd.DataFrame()


class OpenFEMAHmgpAdapter(_OpenFEMABase):
    source_id = "fema_hmgp"
    endpoint_url = OPENFEMA_HMGP_URL
    data_key = "HazardMitigationGrantProgramDisasterSummaries"

    def fetch(self, query: Query) -> pd.DataFrame:
        rows = self._paginate(build_hmgp_filter(query))
        return pd.DataFrame(rows) if rows else pd.DataFrame()


class OpenFEMANfipClaimsAdapter(_OpenFEMABase):
    source_id = "nfip_claims"
    endpoint_url = OPENFEMA_NFIP_URL
    data_key = "FimaNfipClaims"

    def fetch(self, query: Query) -> pd.DataFrame:
        rows = self._paginate(build_filter(query, root=self.root))
        return pd.DataFrame(rows) if rows else pd.DataFrame()
