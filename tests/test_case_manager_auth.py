"""The Case Manager trusts server identity, never client clearance or actor headers."""

import pytest
from fastapi.testclient import TestClient

from moneysweep.case_manager.repository import SQLiteCaseManagerRepository
from server.backend import case_manager_api
from server.backend.case_manager_app import app


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("PRII_WRITE_TOKEN", TEST_TOKEN)
    monkeypatch.setenv("MONEYSWEEP_CASE_ACTOR", "verified-operator")
    repository = SQLiteCaseManagerRepository(":memory:")
    repository.apply_migration(case_manager_api.MIGRATION_PATH)
    case_manager_api.configure_repository(repository)
    with TestClient(app) as client:
        yield client
    case_manager_api.configure_repository(None)
    repository.connection.close()


TEST_TOKEN = "test-case-service-credential"
AUTH = {"Authorization": f"Bearer {TEST_TOKEN}"}
CASE = {"title": "Investigation", "case_type": "audit", "scope": "bounded"}


@pytest.mark.parametrize(
    "path",
    [
        "",
        "/case_x/evidence-links",
        "/case_x/claims",
        "/case_x/claims/claim_x/evidence-relations",
        "/case_x/contradictions",
        "/case_x/contradictions/contradiction_x/resolution",
        "/case_x/leads",
        "/case_x/leads/lead_x/closure",
        "/case_x/findings",
        "/case_x/findings/finding_x/acceptance",
        "/case_x/snapshots",
    ],
)
def test_every_command_requires_authentication_before_payload_or_database_access(client, path):
    assert client.post("/cases" + path, json={}).status_code == 401
    assert client.get("/cases", headers=AUTH).json() == []


@pytest.mark.parametrize("value", [None, "", "   "])
def test_unconfigured_service_fails_closed(client, monkeypatch, value):
    if value is None:
        monkeypatch.delenv("PRII_WRITE_TOKEN")
    else:
        monkeypatch.setenv("PRII_WRITE_TOKEN", value)
    assert client.post("/cases", headers=AUTH, json=CASE).status_code == 503
    assert client.get("/cases").json() == []


@pytest.mark.parametrize("header", ["Basic token", "Bearer wrong", "Bearer", ""])
def test_invalid_credentials_cannot_read_private_cases_or_write(client, header):
    headers = {"Authorization": header}
    assert client.get("/cases", headers=headers).status_code == 401
    assert client.post("/cases", headers=headers, json=CASE).status_code == 401


@pytest.mark.parametrize("legacy", [{"X-Case-Actor": "admin"}, {"X-Case-Clearance": "restricted"}])
@pytest.mark.parametrize("authenticated", [False, True])
def test_spoofed_identity_is_rejected_even_with_valid_token(client, legacy, authenticated):
    headers = {**(AUTH if authenticated else {}), **legacy}
    assert client.get("/cases", headers=headers).status_code == 400
    assert client.post("/cases", headers=headers, json=CASE).status_code == 400


def test_authenticated_commands_bind_audit_actor_and_anonymous_queries_hide_private_data(client):
    response = client.post("/cases", headers=AUTH, json={**CASE, "visibility": "restricted"})
    assert response.status_code == 201, response.text
    rows = client.get("/cases", headers=AUTH).json()
    case_id = rows[0]["case_id"]
    assert client.get("/cases").json() == []
    assert client.get(f"/cases/{case_id}").status_code == 404
    assert client.get(f"/cases/{case_id}/audit-events").status_code == 404
    events = client.get(f"/cases/{case_id}/audit-events", headers=AUTH).json()
    assert events and all(row["actor"] == "verified-operator" for row in events)
    public = client.post(
        "/cases", headers=AUTH, json={**CASE, "title": "Public", "visibility": "public"}
    )
    assert public.status_code == 201
    assert len(client.get("/cases").json()) == 1


def test_token_rotation_rejects_old_credential(client, monkeypatch):
    rotated = "rotated-test-credential"
    monkeypatch.setenv("PRII_WRITE_TOKEN", rotated)
    assert client.post("/cases", headers=AUTH, json=CASE).status_code == 401
    response = client.post("/cases", headers={"Authorization": f"Bearer {rotated}"}, json=CASE)
    assert response.status_code == 201
