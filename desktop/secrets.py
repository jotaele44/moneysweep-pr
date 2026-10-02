"""OS credential-vault integration for MoneySweep API keys.

Secrets are never stored in the MoneySweep workspace, repository, receipts, or
API responses. On macOS the keyring backend uses the user's Keychain. Producers
still consume their historical environment-variable interfaces, so credentials
are exposed to ``os.environ`` only for the duration of a materialization run and
then restored.
"""

from __future__ import annotations

import os
from contextlib import contextmanager

import keyring

SERVICE = "pr.prii.moneysweep"
ALLOWED_KEYS = frozenset(
    {
        "CENSUS_API_KEY",
        "EIA_API_KEY",
        "FAC_API_KEY",
        "FEC_API_KEY",
        "FINANCIALDATA_API_KEY",
        "FRED_API_KEY",
        "HIGHERGOV_API_KEY",
        "OPENSTATES_API_KEY",
        "SAM_API_KEY",
    }
)


def _validate_name(name: str) -> str:
    normalized = str(name or "").strip().upper()
    if normalized not in ALLOWED_KEYS:
        raise ValueError(f"unsupported MoneySweep credential key: {name!r}")
    return normalized


def set_secret(name: str, value: str) -> None:
    key = _validate_name(name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError("credential value must be non-empty")
    keyring.set_password(SERVICE, key, value)


def delete_secret(name: str) -> bool:
    key = _validate_name(name)
    try:
        keyring.delete_password(SERVICE, key)
        return True
    except keyring.errors.PasswordDeleteError:
        return False


def get_secret(name: str) -> str | None:
    key = _validate_name(name)
    try:
        return keyring.get_password(SERVICE, key)
    except Exception:
        # A missing/unavailable backend is an explicit unconfigured state, not a
        # reason to leak backend diagnostics into API responses.
        return None


def presence() -> dict[str, bool]:
    result: dict[str, bool] = {}
    for key in sorted(ALLOWED_KEYS):
        result[key] = bool(os.environ.get(key) or get_secret(key))
    return result


@contextmanager
def activated_credentials():
    """Temporarily expose vault credentials to legacy env-driven producers."""
    previous: dict[str, str | None] = {}
    injected: list[str] = []
    for key in sorted(ALLOWED_KEYS):
        if os.environ.get(key):
            continue
        value = get_secret(key)
        if not value:
            continue
        previous[key] = os.environ.get(key)
        os.environ[key] = value
        injected.append(key)
    try:
        yield tuple(injected)
    finally:
        for key in injected:
            old = previous.get(key)
            if old is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old
