"""Regression gates for the standalone Case Manager authorization boundary."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

pytest.importorskip("fastapi")
pytest.importorskip("httpx")


@pytest.fixture
def client(tmp_path, monkeypatch):
    from starlette.testclient import TestClient
    from moneysweep.case_manager.repository import SQLiteCaseManagerRepository
    from server.backend import case_manager_api
    from server.backend.case_manager_app import app

    for name in ("PRII_WRITE_TOKEN", "MONEYSWEEP_CASE_ACTOR", "MONEYSWEEP_CASE_CLEARANCE"):
        monkeypatch.delenv(name, raising=False)
    repo = SQLiteCaseManagerRepository(tmp_path / "cases.sqlite3")
    repo.apply_migration(case_manager_api.MIGRATION_PATH)
    case_manager_api.configure_repository(repo)
    with TestClient(app) as test_client:
        yield test_client
    case_manager_api.configure_repository(None)
    repo.close()


def payload(title: str) -> dict[str, str]:
    return {"title": title, "case_type": "regression", "scope": "authorization"}


def test_no_configuration_is_public_read_only(client):
    assert client.get("/cases").status_code == 200
    assert client.get("/cases", headers={"X-Case-Clearance": "restricted"}).status_code == 403
    assert client.post("/cases", json=payload("disabled write")).status_code == 503


def test_authenticated_identity_cannot_be_spoofed_or_elevated(client, monkeypatch):
    marker = "fixture-value"
    monkeypatch.setenv("PRII_WRITE_TOKEN", marker)
    monkeypatch.setenv("MONEYSWEEP_CASE_ACTOR", "verified-operator")
    monkeypatch.setenv("MONEYSWEEP_CASE_CLEARANCE", "internal")
    auth = {"Authorization": f"Bearer {marker}"}

    assert client.post("/cases", json=payload("missing auth")).status_code == 401
    assert client.get("/cases", headers={**auth, "X-Case-Clearance": "restricted"}).status_code == 403
    assert client.post(
        "/cases",
        headers={**auth, "X-Case-Actor": "different-actor"},
        json=payload("spoofed actor"),
    ).status_code == 403


def test_authenticated_write_uses_server_identity(client, monkeypatch):
    marker = "fixture-value"
    monkeypatch.setenv("PRII_WRITE_TOKEN", marker)
    monkeypatch.setenv("MONEYSWEEP_CASE_ACTOR", "verified-operator")
    monkeypatch.setenv("MONEYSWEEP_CASE_CLEARANCE", "restricted")

    response = client.post(
        "/cases",
        headers={"Authorization": f"Bearer {marker}"},
        json=payload("verified actor"),
    )
    assert response.status_code == 201
    assert response.json()["audit_event"]["actor"] == "verified-operator"


def test_authenticated_principal_may_request_lower_view(client, monkeypatch):
    marker = "fixture-value"
    monkeypatch.setenv("PRII_WRITE_TOKEN", marker)
    monkeypatch.setenv("MONEYSWEEP_CASE_ACTOR", "verified-operator")
    monkeypatch.setenv("MONEYSWEEP_CASE_CLEARANCE", "restricted")

    response = client.get(
        "/cases",
        headers={"Authorization": f"Bearer {marker}", "X-Case-Clearance": "public"},
    )
    assert response.status_code == 200
