"""HigherGov supplemental adapter — PR-scoped saved-search contracts.

Wraps ``https://highergov.com/api-external/<resource>/`` matching the
existing bulk producer at ``scripts/fetch_highergov_api.py``.

HigherGov's PR scope is encoded by a saved ``search_id`` on their side
rather than a free-form state filter. The base adapter pins the
contract-resource default (the registry's "supplementary federal
contract intel"); subclasses can override ``resource`` and
``search_id`` to fan out to opportunity / IDV / subcontract resources
in a later batch.

``HIGHERGOV_API_KEY`` is **required**. :class:`CredentialMissing` is
raised before any HTTP call when the env var is unset, matching
:class:`FECPRAdapter`.
"""

from __future__ import annotations

import os
from typing import Any

import pandas as pd

from contract_sweeper.runtime.pagination_runtime import PageResult, paginate
from contract_sweeper.runtime.retry_runtime import RetryPolicy, with_retry

from ..types import CredentialMissing, Query
from .base import SourceAdapter

HIGHERGOV_BASE = "https://highergov.com/api-external"
ENV_VAR = "HIGHERGOV_API_KEY"
PAGE_SIZE = 2000
MAX_PAGES = 50


class HigherGovSupplementalAdapter(SourceAdapter):
    source_id = "highergov_supplemental"

    #: HigherGov resource path segment (e.g. ``contract``, ``opportunity``,
    #: ``idv``, ``subcontract``). Default mirrors the producer's prime-
    #: contract pull.
    resource: str = "contract"

    #: Saved-search ID encoding the PR scope on HigherGov's side. The
    #: default value is the contract resource's PR-scoped search from
    #: ``scripts/fetch_highergov_api.py``.
    search_id: str = "O1czhtUyFqdyKMpmMJNvm"

    def __init__(self, *, root, session=None, api_key: str | None = None):
        super().__init__(root=root)
        self._session = session
        self._api_key = api_key

    def _resolved_api_key(self) -> str:
        key = self._api_key or os.environ.get(ENV_VAR, "").strip()
        if not key:
            raise CredentialMissing(self.source_id, ENV_VAR)
        return key

    def _get_session(self):
        if self._session is not None:
            return self._session
        import requests

        s = requests.Session()
        s.headers.update({"Accept": "application/json", "User-Agent": "contract-sweeper-query/1"})
        return s

    def _endpoint(self) -> str:
        return f"{HIGHERGOV_BASE}/{self.resource}/"

    def _get(self, session, params: dict[str, Any]):
        resp = session.get(self._endpoint(), params=params, timeout=60)
        resp.raise_for_status()
        return resp.json()

    @staticmethod
    def _extract_records(payload: Any) -> list[dict]:
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            for key in ("results", "data", "items", "rows", "hits"):
                value = payload.get(key)
                if isinstance(value, list):
                    return value
            for value in payload.values():
                if isinstance(value, list):
                    return value
        return []

    def fetch(self, query: Query) -> pd.DataFrame:
        api_key = self._resolved_api_key()
        session = self._get_session()
        policy = RetryPolicy(max_attempts=4, base_delay_seconds=1.0, max_delay_seconds=15.0)

        def fetch_page(marker):
            page = int(marker) if marker else 1
            params: dict[str, Any] = {
                "api_key": api_key,
                "search_id": self.search_id,
                "page_size": PAGE_SIZE,
                "page": page,
            }
            data = with_retry(lambda: self._get(session, params), policy=policy)
            records = self._extract_records(data)
            has_more = len(records) >= PAGE_SIZE
            return PageResult(records=records, next_marker=(page + 1) if has_more else None)

        rows = list(paginate(fetch_page, start_marker=1, max_pages=MAX_PAGES))
        return pd.DataFrame(rows) if rows else pd.DataFrame()
