"""USAspending adapters — prime awards, subawards, and grants.

Targets the public `spending_by_award` endpoint with a place-of-performance
filter that includes both the PR state code and (when the caller passes
municipalities) the 3-digit county FIPS suffix derived from the canonical
PR municipalities reference table.

Endpoint and request shape mirror the existing bulk producers at
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
GRANT_TYPE_CODES = ["02", "03", "04", "05"]
DIRECT_PAYMENT_TYPE_CODES = ["06"]
LOAN_TYPE_CODES = ["07", "08"]
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

SUBAWARD_FIELDS = [
    "Sub-Award ID",
    "Sub-Awardee Name",
    "Sub-Award Amount",
    "Sub-Award Date",
    "Prime Award ID",
    "Prime Recipient Name",
    "Awarding Agency",
    "Place of Performance State Code",
    "Place of Performance County Name",
    "Place of Performance City",
    "Description",
]


def _municipalities_to_county_suffixes(municipalities: tuple[str, ...], root) -> list[str]:
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


def _build_filters(
    query: Query,
    *,
    root,
    type_codes: list[str],
    subawards: bool,
) -> dict[str, Any]:
    counties = _municipalities_to_county_suffixes(query.municipalities, root)
    if counties:
        locations = [{"country": "USA", "state": "PR", "county": c} for c in counties]
    else:
        locations = [{"country": "USA", "state": "PR"}]
    start, end = _date_window(query)
    filters: dict[str, Any] = {
        "award_type_codes": type_codes,
        "time_period": [{"start_date": start, "end_date": end}],
        "place_of_performance_locations": locations,
    }
    if subawards:
        filters["subawards"] = True
    if query.agencies:
        filters["agencies"] = [
            {"type": "awarding", "tier": "toptier", "name": a} for a in query.agencies
        ]
    if query.recipient_ueis:
        filters["recipient_search_text"] = list(query.recipient_ueis)
    return filters


def _inject_program_numbers(
    payload: dict[str, Any], program_numbers: tuple[str, ...]
) -> dict[str, Any]:
    """Add CFDA program numbers to a payload's filters if not already present."""
    if program_numbers and "program_numbers" not in payload["filters"]:
        payload["filters"]["program_numbers"] = list(program_numbers)
    return payload


def build_payload(query: Query, *, root, page: int = 1) -> dict[str, Any]:
    """Backward-compatible payload builder for the prime adapter (contracts)."""
    return {
        "filters": _build_filters(
            query, root=root, type_codes=CONTRACT_TYPE_CODES, subawards=False
        ),
        "fields": PRIME_FIELDS,
        "page": page,
        "limit": PAGE_LIMIT,
        "sort": "Award Amount",
        "order": "desc",
    }


class _USAspendingBase(SourceAdapter):
    """Shared HTTP + pagination scaffolding for USAspending adapters."""

    type_codes: list[str] = CONTRACT_TYPE_CODES
    subawards: bool = False
    fields: list[str] = PRIME_FIELDS
    sort_field: str = "Award Amount"

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

    def _payload(self, query: Query, page: int) -> dict[str, Any]:
        return {
            "filters": _build_filters(
                query, root=self.root, type_codes=self.type_codes, subawards=self.subawards
            ),
            "fields": self.fields,
            "page": page,
            "limit": PAGE_LIMIT,
            "sort": self.sort_field,
            "order": "desc",
        }

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
                lambda: self._post(session, self._payload(query, page)),
                policy=policy,
            )
            records = data.get("results", []) or []
            meta = data.get("page_metadata", {}) or {}
            has_next = bool(meta.get("hasNext"))
            return PageResult(records=records, next_marker=(page + 1) if has_next else None)

        rows = list(paginate(fetch_page, start_marker=1, max_pages=MAX_PAGES))
        if not rows:
            return pd.DataFrame(columns=self.fields)
        return pd.DataFrame(rows)


class USAspendingPrimeAdapter(_USAspendingBase):
    source_id = "usaspending_prime"
    type_codes = CONTRACT_TYPE_CODES
    subawards = False
    fields = PRIME_FIELDS


class USAspendingSubawardsAdapter(_USAspendingBase):
    """USAspending subawards (both grant and contract subawards merged)."""

    source_id = "usaspending_subawards"
    # Subawards filter accepts either grant or contract type codes; the API
    # then returns all subawards under prime awards of those types. Use the
    # union to capture both flows.
    type_codes = CONTRACT_TYPE_CODES + GRANT_TYPE_CODES
    subawards = True
    fields = SUBAWARD_FIELDS
    sort_field = "Sub-Award Amount"


class USAspendingGrantsAdapter(_USAspendingBase):
    """USAspending grant awards (registry source_id `grants_gov`)."""

    source_id = "grants_gov"
    type_codes = GRANT_TYPE_CODES
    subawards = False
    fields = PRIME_FIELDS
    sort_field = "Award Amount"


# ---------------------------------------------------------------------------
# Per-agency USAspending grant adapters
# ---------------------------------------------------------------------------
# These mirror the existing bulk producers under scripts/download_<agency>.py
# (each pins one toptier `awarding agency` and pulls grant-type-coded
# awards for PR). All they need is the agency_name; the shared
# _USAspendingAgencyGrantsAdapter handles the rest.


class _USAspendingAgencyGrantsAdapter(_USAspendingBase):
    """Base for the per-agency grants adapters.

    Subclasses set `source_id` and `agency_name`. The agency is injected
    into the outgoing payload's `filters.agencies` only when the caller
    didn't already specify one — so a caller can still narrow further if
    they want.
    """

    type_codes = GRANT_TYPE_CODES
    subawards = False
    fields = PRIME_FIELDS
    sort_field = "Award Amount"
    agency_name: str = ""

    def _payload(self, query: Query, page: int) -> dict[str, Any]:
        from dataclasses import replace

        effective = query
        if not query.agencies and self.agency_name:
            effective = replace(query, agencies=(self.agency_name,))
        return super()._payload(effective, page)


class EPAGrantsAdapter(_USAspendingAgencyGrantsAdapter):
    source_id = "epa_grants"
    agency_name = "Environmental Protection Agency"


class DOTGrantsAdapter(_USAspendingAgencyGrantsAdapter):
    source_id = "dot_grants"
    agency_name = "Department of Transportation"


class EDGrantsAdapter(_USAspendingAgencyGrantsAdapter):
    source_id = "ed_grants"
    agency_name = "Department of Education"


class HHSGrantsAdapter(_USAspendingAgencyGrantsAdapter):
    source_id = "hhs_grants"
    agency_name = "Department of Health and Human Services"


class DOEGrantsAdapter(_USAspendingAgencyGrantsAdapter):
    source_id = "doe_grants"
    agency_name = "Department of Energy"


class DOJGrantsAdapter(_USAspendingAgencyGrantsAdapter):
    source_id = "doj_grants"
    agency_name = "Department of Justice"


class USDAGrantsAdapter(_USAspendingAgencyGrantsAdapter):
    source_id = "usda_grants"
    agency_name = "Department of Agriculture"


class OIAGrantsAdapter(_USAspendingAgencyGrantsAdapter):
    source_id = "oia_grants"
    agency_name = "Department of the Interior"


# ---------------------------------------------------------------------------
# USAspending program-narrow adapters (Treasury SLFRF / HAF, EXIM Bank)
# ---------------------------------------------------------------------------
# These pin both an agency and (optionally) a CFDA program number list,
# mirroring the existing bulk producers under scripts/download_<source>.py.
# Where the producer fetches multiple type-code groups in separate passes,
# the adapter unions those codes into a single award_type_codes filter —
# USAspending's spending_by_award endpoint accepts heterogeneous codes.


class _USAspendingNarrowAdapter(_USAspendingAgencyGrantsAdapter):
    """Pins agency, an optional sub-agency, and program_numbers when the caller
    leaves them empty."""

    program_numbers: tuple[str, ...] = ()
    sub_agency_name: str = ""

    def _payload(self, query: Query, page: int) -> dict[str, Any]:
        payload = super()._payload(query, page)
        payload = _inject_program_numbers(payload, self.program_numbers)
        if self.sub_agency_name and not query.agencies:
            agencies = payload["filters"].setdefault("agencies", [])
            already = any(
                a.get("tier") == "subtier" and a.get("name") == self.sub_agency_name
                for a in agencies
            )
            if not already:
                agencies.append(
                    {"type": "awarding", "tier": "subtier", "name": self.sub_agency_name}
                )
        return payload


class SLFRFAdapter(_USAspendingNarrowAdapter):
    source_id = "slfrf"
    agency_name = "Department of the Treasury"
    type_codes = GRANT_TYPE_CODES + CONTRACT_TYPE_CODES + DIRECT_PAYMENT_TYPE_CODES


class HAFAdapter(_USAspendingNarrowAdapter):
    source_id = "haf"
    agency_name = "Department of the Treasury"
    program_numbers = ("21.026",)
    type_codes = GRANT_TYPE_CODES


class EXIMBankAdapter(_USAspendingNarrowAdapter):
    source_id = "exim_bank"
    agency_name = "Export-Import Bank of the United States"
    type_codes = GRANT_TYPE_CODES + DIRECT_PAYMENT_TYPE_CODES + LOAN_TYPE_CODES


# Agency + CFDA narrows mirroring the USASpending fallbacks in the bulk producers
# (scripts/download_<source>.py). Each pins the awarding agency and, where the
# producer fetches specific CFDA programs, the same program_numbers.


class VABenefitsAdapter(_USAspendingNarrowAdapter):
    source_id = "va_benefits"
    agency_name = "Department of Veterans Affairs"
    # VA awards span grants, contracts, and direct-payment benefits.
    type_codes = GRANT_TYPE_CODES + CONTRACT_TYPE_CODES + DIRECT_PAYMENT_TYPE_CODES


class WIOAAdapter(_USAspendingNarrowAdapter):
    source_id = "wioa"
    agency_name = "Department of Labor"
    # WIOA Title I: Adult / Dislocated Worker / Youth.
    program_numbers = ("17.258", "17.259", "17.278")
    type_codes = GRANT_TYPE_CODES


class WICAdapter(_USAspendingNarrowAdapter):
    source_id = "wic"
    agency_name = "Department of Agriculture"
    program_numbers = ("10.557",)  # Special Supplemental Nutrition Program (WIC)
    type_codes = GRANT_TYPE_CODES


class SNAPNAPAdapter(_USAspendingNarrowAdapter):
    source_id = "snap_nap"
    agency_name = "Department of Agriculture"
    # SNAP / Summer Food / NAP-adjacent USDA FNS programs.
    program_numbers = ("10.551", "10.559", "10.568")
    type_codes = GRANT_TYPE_CODES


class HUDHCVSection8Adapter(_USAspendingNarrowAdapter):
    source_id = "hud_hcv_section8"
    agency_name = "Department of Housing and Urban Development"
    program_numbers = ("14.871",)  # Housing Choice Vouchers (Section 8)
    type_codes = GRANT_TYPE_CODES


class USACECivilWorksAdapter(_USAspendingNarrowAdapter):
    source_id = "usace_civil_works"
    agency_name = "Department of Defense"
    sub_agency_name = "U.S. Army Corps of Engineers"
    # USACE civil works spans grants (02-05) and contracts (A-D).
    type_codes = GRANT_TYPE_CODES + CONTRACT_TYPE_CODES
