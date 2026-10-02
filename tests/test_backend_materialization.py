from __future__ import annotations

import json

import pytest

from server.backend.materialization_security import public_run_summary, write_offline_receipt

pytest.importorskip("fastapi")
pytest.importorskip("httpx")


def test_offline_receipt_path_is_independent_of_source_metadata(tmp_path):
    receipt = write_offline_receipt(
        tmp_path,
        {
            "source_id": "../../outside",
            "raw_filename": "../operator-export.csv",
            "sha256": "a" * 64,
        },
    )

    receipt_path = tmp_path / "receipts" / "offline_ingest" / f"{receipt['receipt_id']}.json"
    assert receipt_path.is_file()
    assert receipt_path.parent == tmp_path / "receipts" / "offline_ingest"
    assert json.loads(receipt_path.read_text(encoding="utf-8")) == receipt


def test_public_run_summary_excludes_internal_paths_and_exception_details():
    public = public_run_summary(
        {
            "schema_version": "1.0.0",
            "selected_count": 1,
            "selected": ["test-source"],
            "registry_root": "/private/immutable-registry",
            "workspace_root": "/private/operator-workspace",
            "workspace_rebind": {"PROJECT_ROOT": "/private/operator-workspace"},
            "ran": [
                {
                    "source": "test-source",
                    "status": "ERROR",
                    "rows": None,
                    "error": "RuntimeError: credential=secret-value",
                }
            ],
            "error_count": 1,
        }
    )

    assert public == {
        "schema_version": "1.0.0",
        "selected_count": 1,
        "selected": ["test-source"],
        "error_count": 1,
        "ran": [
            {
                "source": "test-source",
                "status": "ERROR",
                "rows": None,
                "error_code": "ERROR",
            }
        ],
    }


# Every route in server/backend/materialization.py controls the OS credential
# vault or accepts arbitrary uploads/producer execution and is mounted on the
# desktop app with no other auth layer, so every route must reject a request
# that did not originate on the loopback interface (see
# server/backend/local_request.py and server/backend/api_keys.py, which the
# router-level `dependencies=[Depends(require_loopback)]` mirrors). This app
# includes only the materialization router directly -- not the full desktop
# composition root in server/backend/desktop_app.py, which additionally
# requires a bootstrapped MONEYSWEEP_DATA_ROOT workspace unrelated to this
# auth boundary.
@pytest.fixture
def materialization_app():
    # Matches tests/test_desktop_secrets.py's convention: skip cleanly on a
    # pytest job that lacks the keyring backend materialization.py imports.
    pytest.importorskip("keyring")
    from fastapi import FastAPI

    from server.backend.materialization import router as materialization_router

    app = FastAPI()
    app.include_router(materialization_router)
    return app


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/materialization/status"),
        ("GET", "/materialization/sources"),
        ("GET", "/materialization/credentials"),
        ("PUT", "/materialization/credentials/SAM_API_KEY"),
        ("DELETE", "/materialization/credentials/SAM_API_KEY"),
        ("POST", "/materialization/offline/upload"),
        ("POST", "/materialization/offline/some-source/run"),
        ("POST", "/materialization/api/run"),
    ],
)
def test_materialization_routes_reject_nonloopback_client(materialization_app, method, path):
    from starlette.testclient import TestClient

    with TestClient(materialization_app, client=("203.0.113.10", 50000)) as remote_client:
        response = remote_client.request(
            method, path, json={} if method in {"PUT", "POST"} else None
        )

    assert response.status_code == 403


def test_materialization_credentials_route_is_reachable_from_loopback(materialization_app):
    from starlette.testclient import TestClient

    with TestClient(materialization_app, client=("127.0.0.1", 50000)) as local_client:
        response = local_client.get("/materialization/credentials")

    assert response.status_code == 200
    body = response.json()
    assert body["secretsReturned"] is False
