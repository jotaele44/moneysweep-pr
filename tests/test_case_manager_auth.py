"""HTTP-level guards for the Case Manager authorization boundary (finding D4).

Before this, ``case_manager_api`` read the acting identity and the read
clearance straight off client headers (``_actor``/``_clearance`` returned
``value or "anonymous"`` / ``value or "public"``), so any caller could write
audit history under any name and read restricted records by asserting
``X-Case-Clearance: restricted``. These tests pin the two properties that fix
has to hold, plus the boundary conditions around them.

Note the ``client=("127.0.0.1", …)`` argument on every TestClient: starlette's
default peer host is the literal string ``"testclient"``, which the loopback
guard correctly rejects. Without it every assertion here would pass with a 403
while proving nothing.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from server.backend import case_manager_api
from server.backend.case_manager_app import app

INTERNAL_TOKEN = "internal-token-for-tests"
RESTRICTED_TOKEN = "restricted-token-for-tests"
LOOPBACK = ("127.0.0.1", 40000)
OFF_BOX = ("10.0.0.5", 40000)

NEW_CASE = {"title": "Probe", "case_type": "audit", "status": "open", "scope": "s"}


def _identity_file(tmp_path: Path) -> Path:
    path = tmp_path / "identities.json"
    path.write_text(
        json.dumps(
            [
                {
                    "token_sha256": hashlib.sha256(INTERNAL_TOKEN.encode()).hexdigest(),
                    "actor": "analyst@prii",
                    "clearance": "internal",
                },
                {
                    "token_sha256": hashlib.sha256(RESTRICTED_TOKEN.encode()).hexdigest(),
                    "actor": "lead@prii",
                    "clearance": "restricted",
                },
            ]
        ),
        encoding="utf-8",
    )
    return path


@pytest.fixture
def configured(tmp_path, monkeypatch):
    """A loopback client against a fresh database and a real identity file."""
    monkeypatch.setenv("MONEYSWEEP_CASE_DB", str(tmp_path / "case.sqlite3"))
    monkeypatch.setenv("MONEYSWEEP_CASE_IDENTITIES", str(_identity_file(tmp_path)))
    monkeypatch.setattr(case_manager_api, "DATABASE_PATH", tmp_path / "case.sqlite3")
    case_manager_api.configure_repository(None)
    yield TestClient(app, client=LOOPBACK)
    case_manager_api.configure_repository(None)


@pytest.fixture
def unconfigured(tmp_path, monkeypatch):
    """A loopback client with no identity store present."""
    monkeypatch.setenv("MONEYSWEEP_CASE_DB", str(tmp_path / "case.sqlite3"))
    monkeypatch.setenv("MONEYSWEEP_CASE_IDENTITIES", str(tmp_path / "absent.json"))
    monkeypatch.setattr(case_manager_api, "DATABASE_PATH", tmp_path / "case.sqlite3")
    case_manager_api.configure_repository(None)
    yield TestClient(app, client=LOOPBACK)
    case_manager_api.configure_repository(None)


def _auth(token: str) -> dict[str, str]:
    return {"X-Case-Token": token}


# --- fail closed --------------------------------------------------------------


def test_unconfigured_store_refuses_instead_of_falling_back(unconfigured):
    """An unconfigured deployment must refuse, never revert to anonymous/public.

    This is the assertion that matters most: the pre-D4 behavior must not be
    reachable by simply leaving the env var unset.
    """
    assert unconfigured.get("/cases").status_code == 503
    assert unconfigured.post("/cases", json=NEW_CASE).status_code == 503


# --- credential required ------------------------------------------------------


def test_read_without_token_is_rejected(configured):
    assert configured.get("/cases").status_code == 401


def test_write_without_token_is_rejected(configured):
    assert configured.post("/cases", json=NEW_CASE).status_code == 401


def test_unknown_token_is_rejected(configured):
    assert configured.get("/cases", headers=_auth("not-a-real-token")).status_code == 401


def test_valid_token_is_accepted(configured):
    assert configured.get("/cases", headers=_auth(INTERNAL_TOKEN)).status_code == 200


# --- the two vulnerabilities --------------------------------------------------


def test_clearance_header_alone_grants_nothing(configured):
    """The old escalation path: assert restricted clearance, get restricted data."""
    response = configured.get("/cases", headers={"X-Case-Clearance": "restricted"})
    assert response.status_code == 401


def test_clearance_comes_from_the_token_not_the_header(configured):
    """An internal identity cannot reach a restricted case, header or no header."""
    sealed = configured.post(
        "/cases",
        headers=_auth(RESTRICTED_TOKEN),
        json={**NEW_CASE, "title": "Sealed", "visibility": "restricted"},
    ).json()["object"]["case_id"]

    visible_to_restricted = [
        case["case_id"] for case in configured.get("/cases", headers=_auth(RESTRICTED_TOKEN)).json()
    ]
    visible_to_internal = [
        case["case_id"] for case in configured.get("/cases", headers=_auth(INTERNAL_TOKEN)).json()
    ]
    assert sealed in visible_to_restricted
    assert sealed not in visible_to_internal

    assert configured.get(f"/cases/{sealed}", headers=_auth(INTERNAL_TOKEN)).status_code == 404
    # Supplying the header the old code trusted must not change the outcome.
    forged = configured.get(
        f"/cases/{sealed}",
        headers={**_auth(INTERNAL_TOKEN), "X-Case-Clearance": "restricted"},
    )
    assert forged.status_code == 404


def test_audit_actor_comes_from_the_token_not_the_header(configured):
    """The old forgery path: write history under an arbitrary actor name."""
    event = configured.post(
        "/cases",
        headers={**_auth(INTERNAL_TOKEN), "X-Case-Actor": "ceo@evil"},
        json=NEW_CASE,
    ).json()["audit_event"]
    assert event["actor"] == "analyst@prii"
    assert event["actor"] != "ceo@evil"


# --- transport boundary -------------------------------------------------------


def test_off_box_caller_is_rejected_even_with_a_valid_token(tmp_path, monkeypatch):
    monkeypatch.setenv("MONEYSWEEP_CASE_DB", str(tmp_path / "case.sqlite3"))
    monkeypatch.setenv("MONEYSWEEP_CASE_IDENTITIES", str(_identity_file(tmp_path)))
    monkeypatch.setattr(case_manager_api, "DATABASE_PATH", tmp_path / "case.sqlite3")
    case_manager_api.configure_repository(None)
    remote = TestClient(app, client=OFF_BOX)
    try:
        assert remote.get("/cases", headers=_auth(INTERNAL_TOKEN)).status_code == 403
        assert (
            remote.post("/cases", headers=_auth(INTERNAL_TOKEN), json=NEW_CASE).status_code == 403
        )
    finally:
        case_manager_api.configure_repository(None)
