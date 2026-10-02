"""Tests for the /api-keys FastAPI routes (server/backend/api_keys.py).

Mirrors tests/test_server_smoke.py's conventions: real ASGI lifespan via
`with TestClient(app)`, `importorskip` so this test skips cleanly on the
pytest job that runs without fastapi installed, and function-local imports
for every non-stdlib/first-party module (see that file's docstring for why).

scripts.manage_api_keys.ENV_PATH is monkeypatched to a tmp_path for every
test here — the real repo .env is never read or written by this file.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from scripts.manage_api_keys import known_keys

REPO_ROOT = Path(__file__).resolve().parents[1]
REAL_EXAMPLE = REPO_ROOT / ".env.example"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

pytest.importorskip("fastapi")
pytest.importorskip("httpx")


@pytest.fixture
def isolated_env(tmp_path, monkeypatch):
    """Point the api-key store at a throwaway .env for this test only."""
    import scripts.manage_api_keys as manage_module

    env_path = tmp_path / ".env"
    monkeypatch.setattr(manage_module, "ENV_PATH", env_path)
    return env_path


@pytest.fixture
def client(isolated_env):
    from starlette.testclient import TestClient

    import server.backend.main as backend

    with TestClient(backend.app, client=("127.0.0.1", 50000)) as test_client:
        yield test_client


def test_list_api_keys_never_includes_a_value(client):
    response = client.get("/api-keys")
    assert response.status_code == 200
    rows = response.json()
    registry = known_keys(REAL_EXAMPLE)
    expected_names = {key.name for key in registry}
    actual_names = [row["name"] for row in rows]
    assert len(expected_names) == len(registry)
    assert len(actual_names) == len(expected_names)
    assert set(actual_names) == expected_names
    for row in rows:
        assert set(row.keys()) == {"name", "description", "required", "is_set"}


def test_post_unknown_key_returns_404(client):
    response = client.post("/api-keys/NOT_A_REAL_KEY", json={"value": "x"})
    assert response.status_code == 404
    assert "x" not in response.text


@pytest.mark.parametrize("name", ["MONEYSWEEP_CORS_ORIGINS", "MONEYSWEEP_CASE_DB"])
def test_post_noncredential_configuration_returns_404(client, name):
    response = client.post(f"/api-keys/{name}", json={"value": "unsafe-remote-override"})
    assert response.status_code == 404


def test_post_known_key_sets_it_and_never_echoes_the_value(client):
    # Deliberately not a real-credential-shaped string (e.g. no "sk-" prefix)
    # so this fixture doesn't itself trip scripts/scan_for_secrets.py.
    secret = "fixture-value-for-sam-key-test"
    response = client.post("/api-keys/SAM_API_KEY", json={"value": secret})
    assert response.status_code == 200
    assert response.json() == {"name": "SAM_API_KEY", "is_set": True}
    assert secret not in response.text

    follow_up = client.get("/api-keys")
    assert secret not in follow_up.text
    sam_row = next(row for row in follow_up.json() if row["name"] == "SAM_API_KEY")
    assert sam_row["is_set"] is True


def test_post_empty_value_is_rejected(client):
    response = client.post("/api-keys/SAM_API_KEY", json={"value": "  "})
    assert response.status_code == 422


@pytest.mark.parametrize("value", ["first\nINJECTED=value", "first\rsecond", "x\0y"])
def test_post_rejects_values_that_can_escape_one_dotenv_line(client, value):
    response = client.post("/api-keys/SAM_API_KEY", json={"value": value})
    assert response.status_code == 422


def test_post_rejects_nonlocal_origin(client):
    response = client.post(
        "/api-keys/SAM_API_KEY",
        json={"value": "not-written"},
        headers={"Origin": "https://attacker.example"},
    )
    assert response.status_code == 403


def test_api_key_status_rejects_nonloopback_client(isolated_env):
    from starlette.testclient import TestClient

    import server.backend.main as backend

    with TestClient(backend.app, client=("203.0.113.10", 50000)) as remote_client:
        assert remote_client.get("/api-keys").status_code == 403
        response = remote_client.post("/api-keys/SAM_API_KEY", json={"value": "not-written"})
        assert response.status_code == 403
    assert not isolated_env.exists()


def test_set_key_never_touches_real_repo_env(client, isolated_env):
    real_env = REPO_ROOT / ".env"
    existed_before = real_env.exists()

    client.post("/api-keys/SAM_API_KEY", json={"value": "should-stay-local-to-tmp-path"})

    assert real_env.exists() == existed_before
    if existed_before:
        assert "should-stay-local-to-tmp-path" not in real_env.read_text()
    assert "should-stay-local-to-tmp-path" in isolated_env.read_text()
