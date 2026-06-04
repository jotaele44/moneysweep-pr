"""
FinancialData.net provider adapter — OPTIONAL public-market enrichment.

Status:
  - OPTIONAL commercial provider, DISABLED BY DEFAULT.
  - Live calls require BOTH:
      FINANCIALDATA_API_KEY        — vendor API key
      FINANCIALDATA_LICENSE_APPROVED=true — explicit license acknowledgement
  - Without either, this provider skips cleanly with a structured readiness
    payload. The pipeline must NOT treat that as a failure.

Endpoints (stubs — all routes go through `_request()` so a test transport can
intercept). Real endpoint paths are placeholders; verify against vendor docs
before any first live call:
  company_information(identifier)
  securities_information(identifier)
  institutional_holdings(identifier)
  investment_adviser_information(identifier)

Tests:
  - Inject a custom transport (any callable matching the Transport protocol) via
    the `transport` constructor arg. The default transport raises if invoked
    without a configured key+license, so a forgotten patch in a test will fail
    loudly rather than reach the network.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Optional

from scripts.providers import MarketEnrichmentProvider, ProviderReadiness

PROVIDER_NAME = "financialdata_net"
PROVIDER_CATEGORY = "optional_commercial_enrichment"

BASE_URL = "https://financialdata.net/api/v1"
DEFAULT_TIMEOUT = 30
DEFAULT_RETRIES = 3
DEFAULT_RETRY_BACKOFF = (2, 4, 8)
DEFAULT_PAGE_SIZE = 100

# Endpoint path table — single source of truth for relative paths.
# Paths are placeholders; confirm against vendor docs before first live call.
ENDPOINTS: dict[str, str] = {
    "company_information":            "/company",
    "securities_information":         "/securities",
    "institutional_holdings":         "/institutional-holdings",
    "investment_adviser_information": "/investment-advisers",
}

# Transport: any callable `(method, url, params, headers, timeout) -> Optional[dict]`.
# Default transport refuses to run without configuration to avoid silent live calls.
Transport = Callable[[str, str, dict, dict, int], Optional[dict]]


def _disabled_transport(method: str, url: str, params: dict, headers: dict, timeout: int) -> Optional[dict]:
    """Refuse to make a network call when the provider is not configured."""
    raise RuntimeError(
        "FinancialData.net live transport invoked without a configured key+license. "
        "Either configure FINANCIALDATA_API_KEY and FINANCIALDATA_LICENSE_APPROVED, "
        "or inject a mock transport for tests."
    )


@dataclass
class FinancialDataNetProvider:
    """Adapter for FinancialData.net. Default-disabled; injectable for tests."""
    api_key: str | None = None
    license_approved: bool = False
    base_url: str = BASE_URL
    timeout: int = DEFAULT_TIMEOUT
    retries: int = DEFAULT_RETRIES
    retry_backoff: tuple[int, ...] = DEFAULT_RETRY_BACKOFF
    page_size: int = DEFAULT_PAGE_SIZE
    transport: Transport | None = None

    provider_name: str = PROVIDER_NAME
    category: str = PROVIDER_CATEGORY

    # ---- readiness / gating ---------------------------------------------------

    def readiness(self) -> ProviderReadiness:
        key_present = bool(self.api_key and str(self.api_key).strip())
        license_approved = bool(self.license_approved)
        if key_present and license_approved:
            status = "ready"
        elif not key_present and not license_approved:
            status = "missing_both"
        elif not key_present:
            status = "missing_key"
        else:
            status = "missing_license"
        return ProviderReadiness(
            provider=PROVIDER_NAME,
            key_present=key_present,
            license_approved=license_approved,
            ready_for_live=key_present and license_approved,
            status=status,
            license_status="approved" if license_approved else "not_approved",
            details={
                "base_url":  self.base_url,
                "endpoints": list(ENDPOINTS.keys()),
            },
        )

    def is_ready(self) -> bool:
        return self.readiness().ready_for_live

    # ---- request plumbing -----------------------------------------------------

    def _effective_transport(self) -> Transport:
        if self.transport is not None:
            return self.transport
        return _disabled_transport

    def _build_headers(self) -> dict[str, str]:
        return {
            "Accept": "application/json",
            "User-Agent": "ContractSweeper/1.0 (optional FinancialData adapter)",
            **({"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}),
        }

    def _request(self, endpoint_key: str, params: dict | None = None) -> dict | None:
        """
        Centralized request entry point.

        - Resolves endpoint path from ENDPOINTS table
        - Adds standard headers / timeout
        - Delegates to the injected (or default) transport
        - Retries transient failures with backoff
        - Returns the parsed dict (or None on hard failure)
        """
        path = ENDPOINTS.get(endpoint_key)
        if path is None:
            raise KeyError(f"Unknown FinancialData endpoint: {endpoint_key}")
        url = f"{self.base_url.rstrip('/')}{path}"
        transport = self._effective_transport()
        last_err: Exception | None = None
        for attempt in range(self.retries):
            try:
                return transport("GET", url, dict(params or {}), self._build_headers(), self.timeout)
            except Exception as exc:
                last_err = exc
                if attempt < self.retries - 1:
                    time.sleep(self.retry_backoff[min(attempt, len(self.retry_backoff) - 1)])
        if last_err is not None:
            # Surface to caller; pipeline-level error handlers decide what to do.
            raise last_err
        return None

    def _paginate(self, endpoint_key: str, params: dict | None = None,
                  max_pages: int = 50) -> Iterable[dict]:
        """Yield records across paginated responses. Transport must respect page/page_size."""
        page = 1
        while page <= max_pages:
            payload = self._request(endpoint_key, {**(params or {}), "page": page, "page_size": self.page_size})
            if not payload:
                return
            records = payload.get("data") or payload.get("results") or []
            if not records:
                return
            for r in records:
                yield r
            if len(records) < self.page_size:
                return
            page += 1

    # ---- endpoint methods (thin wrappers; logic lives in _request/_paginate) --

    def company_information(self, identifier: str, **extra) -> dict | None:
        return self._request("company_information", {"identifier": identifier, **extra})

    def securities_information(self, identifier: str, **extra) -> dict | None:
        return self._request("securities_information", {"identifier": identifier, **extra})

    def institutional_holdings(self, identifier: str, **extra) -> list[dict]:
        return list(self._paginate("institutional_holdings", {"identifier": identifier, **extra}))

    def investment_adviser_information(self, identifier: str, **extra) -> dict | None:
        return self._request("investment_adviser_information", {"identifier": identifier, **extra})


def from_config(api_key: str | None = None,
                license_approved: bool | None = None,
                transport: Transport | None = None) -> FinancialDataNetProvider:
    """Convenience constructor that reads from scripts.config if args are omitted."""
    if api_key is None or license_approved is None:
        # Imported lazily so that this module is importable in environments
        # without the full scripts package.
        from scripts.config import get_financialdata_api_key, is_financialdata_license_approved
        if api_key is None:
            api_key = get_financialdata_api_key()
        if license_approved is None:
            license_approved = is_financialdata_license_approved()
    return FinancialDataNetProvider(
        api_key=api_key,
        license_approved=bool(license_approved),
        transport=transport,
    )


MARKET_PROVIDER: MarketEnrichmentProvider  # type-hint anchor for the protocol check
