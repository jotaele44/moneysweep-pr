from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.backend import ownership_api


def test_ownership_errors_do_not_expose_exception_details(monkeypatch, tmp_path):
    certification_path = tmp_path / "certification.json"
    holdings_path = tmp_path / "holdings.csv"
    certification_path.touch()
    holdings_path.touch()
    monkeypatch.setattr(
        ownership_api, "_paths", lambda: (certification_path, holdings_path)
    )

    def fail(_path):
        raise ValueError("private path and contents")

    monkeypatch.setattr(
        ownership_api,
        "load_certification",
        fail,
    )

    app = FastAPI()
    app.include_router(ownership_api.router)
    client = TestClient(app)

    status_response = client.get("/deep-dive/ownership/status")
    detail_response = client.get("/deep-dive/ownership/BPOP")

    assert status_response.json()["blocker"] == "ownership data could not be resolved"
    assert detail_response.status_code == 503
    assert detail_response.json()["detail"] == "ownership data is temporarily unavailable"
    assert "private path and contents" not in status_response.text
    assert "private path and contents" not in detail_response.text
