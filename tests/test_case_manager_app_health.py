"""Regression test: case_manager_app's /health must reflect real DB state.

It used to unconditionally return {"status": "ok"} regardless of whether the
case database was reachable -- contradicting server/backend/main.py's /health,
which does inspect its data and can return 500. This locks in the fix: /health
here now opens the repository (applying the schema migration on first use,
same as a real request would) and runs a trivial query against it, so a
genuinely broken database surfaces as a 500 instead of a silent "ok".
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

pytest.importorskip("fastapi")
pytest.importorskip("httpx")


def _app_and_api():
    from server.backend import case_manager_api
    from server.backend.case_manager_app import app

    return app, case_manager_api


@pytest.fixture(autouse=True)
def _reset_repository():
    """Each test gets its own repository via the module's own test hook."""
    _, case_manager_api = _app_and_api()
    case_manager_api.configure_repository(None)
    yield
    case_manager_api.configure_repository(None)


def test_health_reports_ok_when_the_case_database_is_reachable():
    from starlette.testclient import TestClient

    from moneysweep.case_manager.repository import SQLiteCaseManagerRepository

    app, case_manager_api = _app_and_api()
    repository = SQLiteCaseManagerRepository(":memory:")
    repository.apply_migration(case_manager_api.MIGRATION_PATH)
    case_manager_api.configure_repository(repository)

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_health_reports_failure_when_the_case_database_is_unreachable():
    """The bug this fix closes: a broken DB must not still answer 200 "ok"."""
    from starlette.testclient import TestClient

    from moneysweep.case_manager.repository import SQLiteCaseManagerRepository

    app, case_manager_api = _app_and_api()
    repository = SQLiteCaseManagerRepository(":memory:")
    repository.apply_migration(case_manager_api.MIGRATION_PATH)
    repository.connection.close()  # simulate a dead/unreachable database
    case_manager_api.configure_repository(repository)

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 500
