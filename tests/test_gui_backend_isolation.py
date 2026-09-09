"""The real API-key write path must not replace operator credentials in GUI tests."""

import importlib.util
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from scripts import manage_api_keys
from server.backend import api_keys


@pytest.mark.parametrize("server_fails", [False, True])
@pytest.mark.parametrize("backend_port", [None, "18279"])
def test_gui_backend_isolates_and_cleans_credential_store(
    tmp_path, monkeypatch, server_fails, backend_port
):
    if backend_port is None:
        monkeypatch.delenv("GUI_BACKEND_PORT", raising=False)
    else:
        monkeypatch.setenv("GUI_BACKEND_PORT", backend_port)
    operator = tmp_path / "operator.env"
    original = b"CENSUS_API_KEY=original-fixture\n"
    operator.write_bytes(original)
    example = tmp_path / "example.env"
    example.write_text("# Optional census key\nCENSUS_API_KEY=\n")
    monkeypatch.setattr(manage_api_keys, "ENV_PATH", operator)
    monkeypatch.setattr(manage_api_keys, "ENV_EXAMPLE_PATH", example)
    monkeypatch.delenv("CENSUS_API_KEY", raising=False)
    script = Path(__file__).resolve().parents[1] / "dashboard/tests/gui_backend.py"
    spec = importlib.util.spec_from_file_location("gui_backend_isolation", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    stores = []

    def serve(application, *, host, port):
        assert (application, host, port) == (
            "server.backend.main:app",
            "127.0.0.1",
            int(backend_port or "8000"),
        )
        isolated = manage_api_keys.ENV_PATH
        stores.append(isolated)
        assert isolated != operator
        app = FastAPI()
        app.include_router(api_keys.router)
        with TestClient(app, client=("127.0.0.1", 50000)) as client:
            response = client.post("/api-keys/CENSUS_API_KEY", json={"value": "gui-fixture"})
            assert response.status_code == 200
            assert response.json() == {"name": "CENSUS_API_KEY", "is_set": True}
        assert isolated.read_bytes() != original
        assert operator.read_bytes() == original
        if server_fails:
            raise RuntimeError("server startup failed")

    monkeypatch.setattr(module.uvicorn, "run", serve)
    if server_fails:
        with pytest.raises(RuntimeError, match="server startup failed"):
            module.main()
    else:
        module.main()
    assert manage_api_keys.ENV_PATH == operator
    assert operator.read_bytes() == original
    assert len(stores) == 1
    assert not stores[0].parent.exists()
