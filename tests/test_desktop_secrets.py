"""Coverage for the desktop OS credential-vault wrapper.

`desktop/secrets.py` had no tests despite being the only path that writes and
reads API credentials, and despite backing three live endpoints in
`server/backend/materialization.py`. Recorded as finding B2 in
`docs/GAP_ANALYSIS_AND_OPTIMIZATION_2026-09.md`.

`keyring` ships in `server/backend/requirements.txt`, which `tests.yml`
installs but `ci.yml`'s pytest job does not, so this module skips cleanly there
-- the same `importorskip` guard `tests/test_case_manager_auth.py` uses for
`fastapi`. The vault itself is always faked: a real backend would make these
tests machine-dependent and could write to the developer's own keychain.
"""

from __future__ import annotations

import os

import pytest

pytest.importorskip("keyring")

import keyring  # noqa: E402

from desktop import secrets  # noqa: E402


class FakeVault:
    """In-memory stand-in for the OS keyring backend."""

    def __init__(self, *, unavailable: bool = False) -> None:
        self.store: dict[tuple[str, str], str] = {}
        self.unavailable = unavailable

    def set_password(self, service: str, key: str, value: str) -> None:
        if self.unavailable:
            raise RuntimeError("no backend")
        self.store[(service, key)] = value

    def get_password(self, service: str, key: str) -> str | None:
        if self.unavailable:
            raise RuntimeError("no backend")
        return self.store.get((service, key))

    def delete_password(self, service: str, key: str) -> None:
        if self.unavailable:
            raise RuntimeError("no backend")
        if (service, key) not in self.store:
            raise keyring.errors.PasswordDeleteError(key)
        del self.store[(service, key)]


@pytest.fixture
def vault(monkeypatch) -> FakeVault:
    fake = FakeVault()
    monkeypatch.setattr(secrets.keyring, "set_password", fake.set_password)
    monkeypatch.setattr(secrets.keyring, "get_password", fake.get_password)
    monkeypatch.setattr(secrets.keyring, "delete_password", fake.delete_password)
    return fake


@pytest.fixture(autouse=True)
def _clear_credential_env(monkeypatch):
    """Never let the developer's own exported keys decide a result."""
    for key in secrets.ALLOWED_KEYS:
        monkeypatch.delenv(key, raising=False)


# --- key validation ----------------------------------------------------------


@pytest.mark.parametrize("raw", ["sam_api_key", "  SAM_API_KEY  ", "Sam_Api_Key"])
def test_key_names_are_normalized(vault: FakeVault, raw: str) -> None:
    secrets.set_secret(raw, "value")
    assert vault.store[(secrets.SERVICE, "SAM_API_KEY")] == "value"


@pytest.mark.parametrize(
    "raw", ["", "   ", None, "NOT_A_REAL_KEY", "PATH", "AWS_SECRET_ACCESS_KEY"]
)
def test_unsupported_key_names_are_refused(raw) -> None:
    with pytest.raises(ValueError, match="unsupported MoneySweep credential key"):
        secrets.get_secret(raw)


def test_allowlist_refuses_writes_too(vault: FakeVault) -> None:
    with pytest.raises(ValueError):
        secrets.set_secret("AWS_SECRET_ACCESS_KEY", "value")
    assert vault.store == {}


# --- set / get / delete ------------------------------------------------------


@pytest.mark.parametrize("value", ["", "   ", None, 0, b"bytes"])
def test_empty_or_non_string_values_are_refused(vault: FakeVault, value) -> None:
    with pytest.raises(ValueError, match="non-empty"):
        secrets.set_secret("FEC_API_KEY", value)
    assert vault.store == {}


def test_round_trip(vault: FakeVault) -> None:
    secrets.set_secret("FEC_API_KEY", "abc123")
    assert secrets.get_secret("FEC_API_KEY") == "abc123"


def test_get_returns_none_for_unset_key(vault: FakeVault) -> None:
    assert secrets.get_secret("EIA_API_KEY") is None


def test_delete_reports_whether_anything_was_removed(vault: FakeVault) -> None:
    secrets.set_secret("EIA_API_KEY", "v")
    assert secrets.delete_secret("EIA_API_KEY") is True
    assert secrets.delete_secret("EIA_API_KEY") is False


def test_get_hides_backend_failure_rather_than_leaking_it(monkeypatch) -> None:
    """An unavailable vault is an unconfigured state, not a diagnostic to surface."""
    broken = FakeVault(unavailable=True)
    monkeypatch.setattr(secrets.keyring, "get_password", broken.get_password)

    assert secrets.get_secret("FRED_API_KEY") is None


# --- presence ----------------------------------------------------------------


def test_presence_covers_every_allowed_key_and_nothing_else(vault: FakeVault) -> None:
    assert set(secrets.presence()) == set(secrets.ALLOWED_KEYS)


def test_presence_reports_vault_and_env_sources(vault: FakeVault, monkeypatch) -> None:
    secrets.set_secret("FRED_API_KEY", "from-vault")
    monkeypatch.setenv("CENSUS_API_KEY", "from-env")

    presence = secrets.presence()

    assert presence["FRED_API_KEY"] is True
    assert presence["CENSUS_API_KEY"] is True
    assert presence["SAM_API_KEY"] is False


def test_presence_never_returns_secret_values(vault: FakeVault) -> None:
    secrets.set_secret("SAM_API_KEY", "super-secret")
    assert all(isinstance(v, bool) for v in secrets.presence().values())
    assert "super-secret" not in repr(secrets.presence())


# --- activated_credentials ---------------------------------------------------


def test_activation_injects_vault_keys_then_restores(vault: FakeVault) -> None:
    secrets.set_secret("SAM_API_KEY", "vault-value")

    with secrets.activated_credentials() as injected:
        assert "SAM_API_KEY" in injected
        assert os.environ["SAM_API_KEY"] == "vault-value"

    assert "SAM_API_KEY" not in os.environ


def test_activation_never_overwrites_an_existing_env_value(vault: FakeVault, monkeypatch) -> None:
    """Producers' historical env interface wins; the vault only fills gaps."""
    secrets.set_secret("SAM_API_KEY", "vault-value")
    monkeypatch.setenv("SAM_API_KEY", "caller-value")

    with secrets.activated_credentials() as injected:
        assert "SAM_API_KEY" not in injected
        assert os.environ["SAM_API_KEY"] == "caller-value"

    assert os.environ["SAM_API_KEY"] == "caller-value"


def test_activation_restores_env_even_when_the_body_raises(vault: FakeVault) -> None:
    secrets.set_secret("EIA_API_KEY", "vault-value")

    def activate_then_fail() -> None:
        with secrets.activated_credentials():
            assert os.environ["EIA_API_KEY"] == "vault-value"
            raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        activate_then_fail()

    # Reachable: pytest.raises suppresses the matching exception. Kept as a call
    # rather than an inline `raise` so static analysis sees the normal-return
    # path too -- CodeQL flagged the inline form as unreachable code.
    assert "EIA_API_KEY" not in os.environ


def test_activation_is_a_no_op_when_the_vault_is_empty(vault: FakeVault) -> None:
    with secrets.activated_credentials() as injected:
        assert injected == ()
