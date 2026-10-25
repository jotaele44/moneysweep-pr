import hashlib
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from scripts import audit_hud_drgr_authorized_sources as audit
from server.backend import materialization as module


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "_workspace", lambda: tmp_path)
    monkeypatch.setattr(module, "resource_root", lambda: tmp_path)
    source = tmp_path / "activity.csv"
    source.write_text("Activity ID,Name\nA-1,Test\n")
    monkeypatch.setattr(audit, "KNOWN_PATHS", [source])
    app = FastAPI()
    app.include_router(module.router)
    return app


@pytest.fixture
def client(app):
    # The materialization router only serves loopback clients (server/backend/
    # local_request.py); TestClient's default host "testclient" is rejected with 403.
    return TestClient(app, client=("127.0.0.1", 50000))


def test_private_network_client_is_not_local(app):
    remote_client = TestClient(app, client=("192.168.1.20", 50000))

    response = remote_client.get("/materialization/hud-drgr/audits")

    assert response.status_code == 403


def test_audit_preserves_snapshots_and_get_does_not_refresh(client, tmp_path, monkeypatch):
    assert client.get("/materialization/hud-drgr/audits").json()["audits"] == []
    assert client.post("/materialization/hud-drgr/audits").status_code == 200
    first = client.get("/materialization/hud-drgr/audits").json()["audits"][0]
    assert first["authorization"] == "UNPROVEN"
    assert first["receipt"]["arithmetic"]["authorized_candidates"] == 1
    raw = open(first["path"], "rb").read()
    assert first["sha256"] == hashlib.sha256(raw).hexdigest()
    assert client.post("/materialization/hud-drgr/audits").status_code == 200
    monkeypatch.setattr(audit, "build_receipt", lambda *_: pytest.fail("GET re-scanned sources"))
    results = client.get("/materialization/hud-drgr/audits").json()
    assert len(results["audits"]) == 2
    assert results["source_refresh"] is False
    assert open(first["path"], "rb").read() == raw


def test_malformed_and_arithmetic_mismatch_are_visible(client, tmp_path):
    client.post("/materialization/hud-drgr/audits")
    row = client.get("/materialization/hud-drgr/audits").json()["audits"][0]
    receipt = row["receipt"]
    receipt["arithmetic"]["total"] = 42
    from pathlib import Path

    path = Path(row["path"])
    path.write_text(json.dumps(receipt))
    assert (
        client.get("/materialization/hud-drgr/audits").json()["audits"][0]["state"]
        == "INVALID_RECEIPT"
    )
    path.write_text("[]")
    assert (
        client.get("/materialization/hud-drgr/audits").json()["audits"][0]["state"]
        == "INVALID_RECEIPT"
    )


def test_run_error_does_not_leak_exception(client, monkeypatch):
    def fail(_):
        raise RuntimeError("secret test fixture")

    monkeypatch.setattr(audit, "build_receipt", fail)
    response = client.post("/materialization/hud-drgr/audits")
    assert response.status_code == 500
    assert "secret" not in response.text
