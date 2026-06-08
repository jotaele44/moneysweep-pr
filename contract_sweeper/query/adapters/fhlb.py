"""FHLB advances adapter — PR member-bank FHLB advances via the FDIC SDI API.

Mirrors ``scripts/download_fhlb.py``: list active PR institutions from the FDIC
``institutions`` endpoint, then read each one's ``FHLBADV`` (FHLB advances
outstanding) from the FDIC ``financials`` (SDI) endpoint by reporting year.

No credentials required.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd

from contract_sweeper.runtime.retry_runtime import RetryPolicy, with_retry

from ..types import Query
from .base import SourceAdapter

FDIC_BASE = "https://banks.data.fdic.gov/api"
FDIC_INSTITUTIONS_URL = f"{FDIC_BASE}/institutions"
FDIC_FINANCIALS_URL = f"{FDIC_BASE}/financials"
MAX_INSTITUTIONS = 500


class FHLBAdvancesAdapter(SourceAdapter):
    source_id = "fhlb"

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

    def _get(self, session, url: str, params: dict[str, Any]):
        resp = session.get(url, params=params, timeout=60)
        resp.raise_for_status()
        return resp.json()

    def _years(self, query: Query) -> list[int]:
        if query.fiscal_years:
            return sorted({int(y) for y in query.fiscal_years})
        return [date.today().year - 1]  # most recent completed call-report year

    def _pr_institutions(self, session, policy) -> list[dict]:
        params = {
            "filters": "STALP:PR AND ACTIVE:1",
            "fields": "CERT,INSTNAME,STALP,ASSET",
            "limit": MAX_INSTITUTIONS,
            "offset": 0,
            "format": "json",
        }
        data = with_retry(lambda: self._get(session, FDIC_INSTITUTIONS_URL, params), policy=policy)
        return [item.get("data", item) for item in (data.get("data") or [])]

    def fetch(self, query: Query) -> pd.DataFrame:
        session = self._get_session()
        policy = RetryPolicy(max_attempts=4, base_delay_seconds=1.0, max_delay_seconds=15.0)

        rows: list[dict] = []
        for inst in self._pr_institutions(session, policy):
            cert = str(inst.get("CERT", "")).strip()
            if not cert:
                continue
            for year in self._years(query):
                params = {
                    "filters": f"CERT:{cert} AND REPDTE:{year}1231",
                    "fields": "CERT,REPDTE,FHLBADV,ASSET",
                    "limit": 10,
                    "format": "json",
                }
                data = with_retry(
                    lambda: self._get(session, FDIC_FINANCIALS_URL, params), policy=policy
                )
                for rec in data.get("data") or []:
                    d = rec.get("data", rec)
                    rows.append(
                        {
                            "cert": cert,
                            "institution_name": inst.get("INSTNAME", ""),
                            "reporting_date": str(d.get("REPDTE", "")),
                            "fiscal_year": str(year),
                            "fhlb_advances_outstanding": d.get("FHLBADV"),
                            "total_assets": d.get("ASSET"),
                            "state": "PR",
                        }
                    )
        return pd.DataFrame(rows) if rows else pd.DataFrame()
