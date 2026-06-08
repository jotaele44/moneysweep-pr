"""CMS Socrata SODA 2.0 adapters (medicare_advantage, medicare_parts).

Wraps ``https://data.cms.gov/resource/<resource_id>.json`` matching
the existing bulk producers at ``scripts/download_medicare_advantage.py``
and ``scripts/download_medicare_parts.py``. CMS year-shards datasets,
so each adapter iterates a hardcoded list of resource IDs and concats
the rows; each result row is tagged with the resource ID it came from
via a ``source_dataset_id`` column.

The ``CMS_APP_TOKEN`` env var is *optional* — Socrata works
unauthenticated at a lower rate limit. Unlike credential-gated
adapters (e.g. FEC, SAM), this adapter does NOT raise
:class:`CredentialMissing` when the token is unset.
"""

from __future__ import annotations

import os
from typing import Any

import pandas as pd

from contract_sweeper.runtime.pagination_runtime import PageResult, paginate
from contract_sweeper.runtime.retry_runtime import RetryPolicy, with_retry

from ..types import Query
from .base import SourceAdapter

SOCRATA_BASE = "https://data.cms.gov/resource"
PAGE_SIZE = 10000
MAX_PAGES = 50
ENV_VAR = "CMS_APP_TOKEN"
DEFAULT_STATE_CLAUSE = "state_code='PR' OR state='PR' OR state='Puerto Rico'"


class _CMSSocrataAdapter(SourceAdapter):
    """Base class for data.cms.gov Socrata SODA 2.0 resources."""

    #: Year-sharded resource IDs to iterate.
    resource_ids: tuple[str, ...] = ()

    #: SoQL ``$where`` clause. CMS datasets are inconsistent about the
    #: state column name; the default OR-list catches the common ones.
    state_clause: str = DEFAULT_STATE_CLAUSE

    def __init__(self, *, root, session=None, app_token: str | None = None):
        super().__init__(root=root)
        self._session = session
        self._app_token = app_token

    def _resolved_app_token(self) -> str | None:
        token = self._app_token or os.environ.get(ENV_VAR, "").strip()
        return token or None

    def _get_session(self):
        if self._session is not None:
            return self._session
        import requests

        s = requests.Session()
        s.headers.update(
            {
                "Accept": "application/json",
                "User-Agent": "contract-sweeper-query/1",
            }
        )
        token = self._resolved_app_token()
        if token:
            s.headers["X-App-Token"] = token
        return s

    def _get(self, session, url: str, params: dict[str, Any]):
        resp = session.get(url, params=params, timeout=60)
        resp.raise_for_status()
        return resp.json()

    def _fetch_resource(self, session, resource_id: str, policy: RetryPolicy) -> list[dict]:
        url = f"{SOCRATA_BASE}/{resource_id}.json"

        def fetch_page(marker):
            offset = int(marker) if marker else 0
            params = {
                "$where": self.state_clause,
                "$limit": PAGE_SIZE,
                "$offset": offset,
            }
            data = with_retry(lambda: self._get(session, url, params), policy=policy)
            records = data if isinstance(data, list) else []
            next_marker = (offset + PAGE_SIZE) if len(records) >= PAGE_SIZE else None
            return PageResult(records=records, next_marker=next_marker)

        rows = list(paginate(fetch_page, start_marker=0, max_pages=MAX_PAGES))
        return [{**row, "source_dataset_id": resource_id} for row in rows]

    def fetch(self, query: Query) -> pd.DataFrame:
        session = self._get_session()
        policy = RetryPolicy(max_attempts=4, base_delay_seconds=1.0, max_delay_seconds=15.0)

        all_rows: list[dict] = []
        for resource_id in self.resource_ids:
            try:
                all_rows.extend(self._fetch_resource(session, resource_id, policy))
            except Exception:  # noqa: BLE001 — one stale resource shouldn't sink the rest
                continue

        return pd.DataFrame(all_rows) if all_rows else pd.DataFrame()


class MedicareAdvantageAdapter(_CMSSocrataAdapter):
    source_id = "medicare_advantage"
    resource_ids = ("qksd-9k7j", "nu5k-459e", "r9ta-rabe")


class MedicarePartsAdapter(_CMSSocrataAdapter):
    source_id = "medicare_parts"
    resource_ids = ("6i6u-frbu", "w96h-y9mq", "tbcw-ytz8")
