"""CKAN metastore + datastore adapters (cms_open_payments, medicaid_fmap, chip).

Wraps the CKAN-style ``/api/1/metastore/schemas/dataset/items`` +
``/api/1/datastore/query/<resource_id>`` surface exposed by both
``openpaymentsdata.cms.gov`` and ``data.medicaid.gov``, matching the
existing bulk producers at ``scripts/download_cms.py``,
``scripts/download_medicaid_fmap.py``, and ``scripts/download_chip.py``.

Each subclass declares the metastore base URL and a list of search
keywords used to find the relevant dataset(s). The adapter discovers
matching datasets, picks a CSV distribution resource for each, and
paginates the datastore-query endpoint filtered to PR.

No credentials required.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from moneysweep.runtime.pagination_runtime import PageResult, paginate
from moneysweep.runtime.retry_runtime import RetryPolicy, with_retry

from ..types import Query
from .base import SourceAdapter

PAGE_SIZE = 10000
MAX_PAGES = 50
MAX_DATASETS = 5


class _CKANMetastoreAdapter(SourceAdapter):
    """Base class for CKAN metastore + datastore endpoints."""

    #: e.g. ``https://data.medicaid.gov/api/1``
    metastore_base: str = ""

    #: Case-insensitive substrings to filter dataset titles.
    search_keywords: tuple[str, ...] = ()

    #: Datastore field name carrying the state.
    pr_filter_field: str = "state"

    #: Values to match against ``pr_filter_field``.
    pr_values: tuple[str, ...] = ("PR", "Puerto Rico", "72")

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
                "User-Agent": "moneysweep-pr-query/1",
            }
        )
        return s

    def _get(self, session, url: str, params: dict[str, Any] | None = None):
        resp = session.get(url, params=params, timeout=60)
        resp.raise_for_status()
        return resp.json()

    def _post(self, session, url: str, payload: dict[str, Any]):
        resp = session.post(url, json=payload, timeout=60)
        resp.raise_for_status()
        return resp.json()

    def _matches_keyword(self, title: str) -> bool:
        if not title or not self.search_keywords:
            return False
        title_lower = title.lower()
        return any(kw.lower() in title_lower for kw in self.search_keywords)

    def _csv_resource_id(self, distributions: list[dict]) -> str | None:
        for dist in distributions:
            mt = (dist.get("mediaType") or "").lower()
            if "csv" in mt or "json" in mt:
                rid = dist.get("identifier") or dist.get("@id") or dist.get("downloadURL")
                if rid:
                    return str(rid).rsplit("/", 1)[-1]
        for dist in distributions:
            rid = dist.get("identifier") or dist.get("@id")
            if rid:
                return str(rid).rsplit("/", 1)[-1]
        return None

    def _discover_resources(self, session, policy: RetryPolicy) -> list[tuple[str, str]]:
        """Return up to MAX_DATASETS (resource_id, dataset_id) pairs whose title matches a keyword."""
        items_url = f"{self.metastore_base}/metastore/schemas/dataset/items"
        data = with_retry(lambda: self._get(session, items_url), policy=policy)
        items = data if isinstance(data, list) else (data.get("items") or [])
        matches: list[tuple[str, str]] = []
        for item in items:
            title = item.get("title") or item.get("name") or ""
            if not self._matches_keyword(title):
                continue
            distributions = item.get("distribution") or []
            resource_id = self._csv_resource_id(distributions)
            if not resource_id:
                continue
            dataset_id = item.get("identifier") or item.get("@id") or ""
            matches.append((resource_id, str(dataset_id)))
            if len(matches) >= MAX_DATASETS:
                break
        return matches

    def _fetch_datastore(self, session, resource_id: str, policy: RetryPolicy) -> list[dict]:
        query_url = f"{self.metastore_base}/datastore/query/{resource_id}"
        conditions = [
            {"resource": "t", "property": self.pr_filter_field, "value": value, "operator": "="}
            for value in self.pr_values
        ]
        payload_base: dict[str, Any] = {
            "conditions": conditions,
            "resources": [{"id": resource_id, "alias": "t"}],
        }

        def fetch_page(marker):
            offset = int(marker) if marker else 0
            payload = dict(payload_base)
            payload["limit"] = PAGE_SIZE
            payload["offset"] = offset
            try:
                data = with_retry(lambda: self._post(session, query_url, payload), policy=policy)
            except Exception:  # noqa: BLE001 — fall back to a simple GET if POST is unsupported
                params = {"limit": PAGE_SIZE, "offset": offset, "conditions": str(conditions)}
                data = with_retry(lambda: self._get(session, query_url, params), policy=policy)
            results = data.get("results") or data.get("records") or data.get("data") or []
            if isinstance(results, dict):
                results = [results]
            next_marker = (offset + PAGE_SIZE) if len(results) >= PAGE_SIZE else None
            return PageResult(records=results, next_marker=next_marker)

        return list(paginate(fetch_page, start_marker=0, max_pages=MAX_PAGES))

    def fetch(self, query: Query) -> pd.DataFrame:
        if not self.metastore_base:
            return pd.DataFrame()
        session = self._get_session()
        policy = RetryPolicy(max_attempts=4, base_delay_seconds=1.0, max_delay_seconds=15.0)

        try:
            resources = self._discover_resources(session, policy)
        except Exception:  # noqa: BLE001 — metastore down ⇒ empty result, not crash
            return pd.DataFrame()
        if not resources:
            return pd.DataFrame()

        all_rows: list[dict] = []
        for resource_id, dataset_id in resources:
            try:
                rows = self._fetch_datastore(session, resource_id, policy)
            except Exception:  # noqa: BLE001 — one bad dataset shouldn't sink the rest
                continue
            all_rows.extend(
                {
                    **row,
                    "source_dataset_id": dataset_id or resource_id,
                    "source_resource_id": resource_id,
                }
                for row in rows
            )

        return pd.DataFrame(all_rows) if all_rows else pd.DataFrame()


class CMSOpenPaymentsAdapter(_CKANMetastoreAdapter):
    source_id = "cms_open_payments"
    metastore_base = "https://openpaymentsdata.cms.gov/api/1"
    search_keywords = ("open payments", "general payment")
    pr_filter_field = "recipient_state"


class MedicaidFMAPAdapter(_CKANMetastoreAdapter):
    source_id = "medicaid_fmap"
    metastore_base = "https://data.medicaid.gov/api/1"
    search_keywords = ("FMAP", "Federal Medical Assistance")


class CHIPAdapter(_CKANMetastoreAdapter):
    source_id = "chip"
    metastore_base = "https://data.medicaid.gov/api/1"
    search_keywords = ("CHIP", "Children's Health Insurance")
