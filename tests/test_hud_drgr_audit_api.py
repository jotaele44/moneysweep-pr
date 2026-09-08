import hashlib
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from scripts import audit_hud_drgr_authorized_sources as audit
from server.backend import hud_drgr_api as module


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "_workspace", lambda: tmp_path)
    monkeypatch.setattr(module, "resource_root", lambda: tmp_path)
    source = tmp_path / "activity.csv"
    source.write_text("Activity ID,Name\nA-1,Test\n")
    monkeypatch.setattr(audit, "KNOWN_PATHS", [source])
    app = FastAPI()
    app.include_router(module.router)
    return TestClient(app, client=("127.0.0.1", 50000))


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


@pytest.mark.parametrize(
    "corruption",
    ["boolean_count", "invalid_time", "claimed_authority", "snapshot_bytes", "snapshot_escape"],
)
def test_invalid_receipt_and_frozen_input_fail_closed(client, tmp_path, corruption):
    from pathlib import Path

    assert client.post("/materialization/hud-drgr/audits").status_code == 200
    row = client.get("/materialization/hud-drgr/audits").json()["audits"][0]
    path = Path(row["path"])
    receipt = row["receipt"]
    if corruption == "boolean_count":
        receipt["arithmetic"]["total"] = True
    elif corruption == "invalid_time":
        receipt["generated_at_utc"] = "not-a-timestamp"
    elif corruption == "claimed_authority":
        receipt["authorization"] = "CERTIFIED"
    elif corruption == "snapshot_bytes":
        (path.parent / receipt["records"][0]["snapshot_relative_path"]).write_bytes(b"changed")
    else:
        receipt["records"][0]["snapshot_relative_path"] = "../../outside.csv"
    path.write_text(json.dumps(receipt))
    response = client.get("/materialization/hud-drgr/audits")
    assert response.status_code == 200
    assert response.json()["audits"][0]["state"] == "INVALID_RECEIPT"


def test_diagnostic_app_mounts_audit_router_without_desktop_credential_dependency(
    client, monkeypatch, tmp_path
):
    from server.backend.main import app

    monkeypatch.setattr(module, "_workspace", lambda: tmp_path)
    with TestClient(app, client=("127.0.0.1", 50000)) as diagnostic:
        response = diagnostic.get("/materialization/hud-drgr/audits")
    assert response.status_code == 200
    assert response.json()["source_refresh"] is False


def test_remote_and_untrusted_origins_cannot_inspect_local_paths(client):
    assert (
        client.get(
            "/materialization/hud-drgr/audits", headers={"Origin": "https://untrusted.example"}
        ).status_code
        == 403
    )
    app = FastAPI()
    app.include_router(module.router)
    with TestClient(app, client=("198.51.100.1", 50000)) as remote:
        assert remote.get("/materialization/hud-drgr/audits").status_code == 403
        assert remote.post("/materialization/hud-drgr/audits").status_code == 403
