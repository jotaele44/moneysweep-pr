"""Canonical MoneySweep credential-name registry.

This module stores metadata and environment-variable NAMES only. Secret values
must never be added here. The registry distinguishes credentials from license
acknowledgements and preserves optional/fallback semantics for providers that
support unauthenticated or demo access.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CredentialSpec:
    name: str
    kind: str
    requirement: str
    provider: str
    vault: bool = True


CREDENTIALS: tuple[CredentialSpec, ...] = (
    CredentialSpec("SAM_API_KEY", "api_key", "required_for_live_api", "sam.gov"),
    CredentialSpec("LDA_API_KEY", "api_key", "optional", "lda.senate.gov"),
    CredentialSpec("FEC_API_KEY", "api_key", "demo_fallback", "fec/api.data.gov"),
    CredentialSpec("FAC_API_KEY", "api_key", "required_for_registered_source", "fac/api.data.gov"),
    CredentialSpec("HIGHERGOV_API_KEY", "api_key", "required_for_registered_source", "highergov"),
    CredentialSpec("DATA_GOV_API_KEY", "api_key", "optional", "api.data.gov"),
    CredentialSpec("CENSUS_API_KEY", "api_key", "optional", "census"),
    CredentialSpec("EIA_API_KEY", "api_key", "required_for_registered_source", "eia"),
    CredentialSpec("FRED_API_KEY", "api_key", "required_for_registered_source", "fred"),
    CredentialSpec("FELT_API_KEY", "api_key", "optional", "felt"),
    CredentialSpec("FINANCIALDATA_API_KEY", "api_key", "license_gated", "financialdata.net"),
    CredentialSpec("X_API_KEY", "api_key", "optional_fallback", "api.data.gov"),
    CredentialSpec("PROPUBLICA_API_KEY", "api_key", "optional", "propublica"),
    CredentialSpec("CMS_APP_TOKEN", "app_token", "optional", "cms-socrata"),
    CredentialSpec("SOCRATA_APP_TOKEN", "app_token", "optional", "oce-socrata"),
    CredentialSpec("OPENSTATES_API_KEY", "api_key", "required_except_audit_mode", "openstates"),
)

LICENSE_GATES = frozenset({"FINANCIALDATA_LICENSE_APPROVED"})
CREDENTIAL_NAMES = frozenset(spec.name for spec in CREDENTIALS)
VAULT_CREDENTIAL_NAMES = frozenset(spec.name for spec in CREDENTIALS if spec.vault)


def credential_spec(name: str) -> CredentialSpec | None:
    normalized = str(name or "").strip().upper()
    return next((spec for spec in CREDENTIALS if spec.name == normalized), None)
