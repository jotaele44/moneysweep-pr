from __future__ import annotations

import re
from pathlib import Path

import yaml

from moneysweep.runtime.credential_registry import (
    CREDENTIAL_NAMES,
    LICENSE_GATES,
    VAULT_CREDENTIAL_NAMES,
)

ROOT = Path(__file__).resolve().parents[1]


def _env_example_credentials() -> set[str]:
    names: set[str] = set()
    for raw in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name = line.split("=", 1)[0].strip()
        if name.endswith(("_API_KEY", "_APP_TOKEN")):
            names.add(name)
    return names


def _registry_credentials() -> set[str]:
    payload = yaml.safe_load((ROOT / "registries/source_registry.yaml").read_text(encoding="utf-8"))
    out: set[str] = set()
    for src in payload.get("sources", []):
        auth = str(src.get("authentication") or "")
        if auth.startswith("api_key:"):
            out.add(auth.split(":", 1)[1].strip())
    return out


def _registry_license_gates() -> set[str]:
    payload = yaml.safe_load((ROOT / "registries/source_registry.yaml").read_text(encoding="utf-8"))
    return {\n        str(src["license_gate"]).strip()\n        for src in payload.get("sources", [])\n        if src.get("license_gate")\n    }


def test_env_example_credential_names_are_canonical() -> None:
    assert _env_example_credentials() <= CREDENTIAL_NAMES


def test_source_registry_api_keys_are_canonical() -> None:
    assert _registry_credentials() <= CREDENTIAL_NAMES


def test_source_registry_license_gates_are_canonical() -> None:
    assert _registry_license_gates() <= LICENSE_GATES


def test_desktop_vault_binds_to_canonical_vault_denominator() -> None:
    text = (ROOT / "desktop/secrets.py").read_text(encoding="utf-8")
    assert "from moneysweep.runtime.credential_registry import VAULT_CREDENTIAL_NAMES" in text
    assert "ALLOWED_KEYS = VAULT_CREDENTIAL_NAMES" in text


def test_registry_contains_names_only_not_secret_values() -> None:
    text = (ROOT / "moneysweep/runtime/credential_registry.py").read_text(encoding="utf-8")
    assert "paste_your_key_here" not in text
    assert not re.search(r"(?m)^[A-Z][A-Z0-9_]*(?:API_KEY|APP_TOKEN)\s*=", text)
