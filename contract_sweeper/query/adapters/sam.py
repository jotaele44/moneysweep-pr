"""SAM.gov entity-mode adapter.

Wraps ``https://api.sam.gov/entity-information/v2/entities`` matching
``scripts/sam_enrichment.py``. Looks up entities one at a time keyed on
UEI, legalBusinessName, or CAGE — SAM has no bulk filter.

``SAM_API_KEY`` is required; :class:`CredentialMissing` is raised before
any HTTP call. Rate limit: 1,000 requests/day per key.
"""
from __future__ import annotations

import os
from typing import Any

import pandas as pd

from contract_sweeper.runtime.retry_runtime import RetryPolicy, with_retry

from ..entity_types import EntityQuery
from ..types import CredentialMissing
from .entity_base import EntityAdapter

SAM_BASE_URL = "https://api.sam.gov/entity-information/v2/entities"
ENV_VAR = "SAM_API_KEY"
PAGE_SIZE = 5

# Map our identifier kinds → SAM query-param names.
PARAM_FOR_KIND: dict[str, str] = {
    "uei": "ueiSAM",
    "name": "legalBusinessName",
    "cage": "cageCode",
    "duns": "ueiDUNS",
}


class SAMEntitiesAdapter(EntityAdapter):
    source_id = "sam_entities"
    supported_kinds = frozenset({"uei", "name", "cage", "duns"})

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
        s.headers.update({
            "Accept": "application/json",
            "User-Agent": "contract-sweeper-query/1",
        })
        return s

    def _get(self, session, params: dict[str, Any]):
        resp = session.get(SAM_BASE_URL, params=params, timeout=60)
        resp.raise_for_status()
        return resp.json()

    def _lookup(self, session, api_key: str, kind: str, value: str, policy: RetryPolicy) -> list[dict]:
        param_name = PARAM_FOR_KIND[kind]
        params: dict[str, Any] = {
            "api_key": api_key,
            param_name: value,
            "registrationStatus": "A",
            "page": 0,
            "size": PAGE_SIZE,
        }
        data = with_retry(lambda: self._get(session, params), policy=policy)
        entities = (data.get("entityData") or []) if isinstance(data, dict) else []
        rows: list[dict] = []
        for ent in entities:
            reg = (ent.get("entityRegistration") or {})
            core = (ent.get("coreData") or {})
            parent = ((core.get("entityHierarchyInformation") or {}).get("immediateParentEntity") or {})
            address = (core.get("physicalAddress") or {})
            rows.append({
                "lookup_kind": kind,
                "lookup_value": value,
                "uei": reg.get("ueiSAM", ""),
                "cage": reg.get("cageCode", ""),
                "duns": reg.get("ueiDUNS", "") or reg.get("dunsNumber", ""),
                "legal_business_name": reg.get("legalBusinessName", ""),
                "registration_status": reg.get("registrationStatus", ""),
                "expiration_date": reg.get("registrationExpirationDate", ""),
                "state": address.get("stateOrProvinceCode", ""),
                "city": address.get("city", ""),
                "parent_uei": parent.get("ueiSAM", ""),
                "parent_name": parent.get("legalBusinessName", ""),
            })
        return rows

    def fetch(self, query: EntityQuery) -> pd.DataFrame:
        api_key = self._resolved_api_key()
        session = self._get_session()
        policy = RetryPolicy(max_attempts=4, base_delay_seconds=1.0, max_delay_seconds=15.0)

        rows: list[dict] = []
        for ident in query.identifiers:
            if ident.kind not in self.supported_kinds:
                continue
            rows.extend(self._lookup(session, api_key, ident.kind, ident.value, policy))

        return pd.DataFrame(rows) if rows else pd.DataFrame()
