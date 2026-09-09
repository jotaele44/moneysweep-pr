"""Authentication and authorization boundary for the standalone Case Manager API.

The Case Manager previously trusted X-Case-Actor and X-Case-Clearance directly.
This middleware preserves those headers only as compatibility inputs: the server
now derives the authenticated actor and maximum clearance from server-side
configuration and rewrites the request headers before FastAPI route binding.

Security contract
-----------------
* Public reads remain available without credentials.
* Privileged reads require a valid PRII_WRITE_TOKEN bearer token.
* Every write requires a configured and valid PRII_WRITE_TOKEN.
* When PRII_WRITE_TOKEN is unset, writes fail closed (503); there is no local/LAN
  bypass for investigative case data.
* X-Case-Clearance may request a lower/equal view but cannot elevate beyond the
  authenticated principal's server-configured clearance.
* X-Case-Actor may only echo the server-derived actor; a mismatched value is
  rejected rather than trusted.
* Credentials are never stored in tracked files.
"""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from typing import Awaitable, Callable

from fastapi import FastAPI, Request
from starlette.responses import JSONResponse, Response

_VISIBILITY_RANK = {"public": 0, "internal": 1, "restricted": 2}
_DEFAULT_ACTOR = "authenticated-case-operator"
_DEFAULT_CLEARANCE = "internal"


@dataclass(frozen=True)
class CasePrincipal:
    actor: str
    clearance: str


def _json_error(status_code: int, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"detail": detail})


def _configured_principal() -> tuple[str, CasePrincipal] | None:
    token = os.environ.get("PRII_WRITE_TOKEN", "")
    if not token:
        return None

    actor = os.environ.get("MONEYSWEEP_CASE_ACTOR", _DEFAULT_ACTOR).strip()
    clearance = os.environ.get("MONEYSWEEP_CASE_CLEARANCE", _DEFAULT_CLEARANCE).strip().lower()
    if not actor:
        raise RuntimeError("MONEYSWEEP_CASE_ACTOR must not be empty when PRII_WRITE_TOKEN is set")
    if clearance not in _VISIBILITY_RANK:
        raise RuntimeError(
            "MONEYSWEEP_CASE_CLEARANCE must be one of public|internal|restricted "
            "when PRII_WRITE_TOKEN is set"
        )
    return token, CasePrincipal(actor=actor, clearance=clearance)


def _presented_bearer(request: Request) -> tuple[bool, str]:
    raw = request.headers.get("authorization", "")
    if not raw:
        return False, ""
    scheme, separator, value = raw.partition(" ")
    if not separator or scheme.lower() != "bearer" or not value:
        return True, ""
    return True, value


def _set_header(request: Request, name: str, value: str) -> None:
    """Replace one request header before FastAPI resolves Header parameters."""
    target = name.lower().encode("latin-1")
    encoded = value.encode("latin-1")
    headers = [(k, v) for k, v in request.scope.get("headers", []) if k.lower() != target]
    headers.append((target, encoded))
    request.scope["headers"] = headers
    # Starlette caches Headers lazily on Request. Drop any cache if a caller has
    # already accessed request.headers before this mutation.
    request.__dict__.pop("_headers", None)


def _requested_clearance(request: Request) -> tuple[str | None, JSONResponse | None]:
    requested = request.headers.get("x-case-clearance")
    if requested is None or requested == "":
        return None, None
    requested = requested.strip().lower()
    if requested not in _VISIBILITY_RANK:
        return None, _json_error(400, "X-Case-Clearance must be public|internal|restricted")
    return requested, None


def install_case_auth(app: FastAPI) -> None:
    """Install the Case Manager security boundary on ``app`` exactly once."""
    if getattr(app.state, "case_auth_installed", False):
        return
    app.state.case_auth_installed = True

    @app.middleware("http")
    async def case_auth_boundary(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if not request.url.path.startswith("/cases"):
            return await call_next(request)

        try:
            configured = _configured_principal()
        except RuntimeError as exc:
            return _json_error(503, str(exc))

        requested_clearance, error = _requested_clearance(request)
        if error is not None:
            return error

        is_write = request.method.upper() not in {"GET", "HEAD", "OPTIONS"}
        auth_supplied, presented = _presented_bearer(request)

        if configured is None:
            if is_write:
                return _json_error(
                    503,
                    "Case Manager writes are disabled until PRII_WRITE_TOKEN is configured",
                )
            if requested_clearance not in {None, "public"}:
                return _json_error(403, "Authentication is required for non-public case data")
            _set_header(request, "x-case-clearance", "public")
            return await call_next(request)

        expected_token, principal = configured
        authenticated = False
        if auth_supplied:
            if not presented or not secrets.compare_digest(presented, expected_token):
                return _json_error(401, "Missing or invalid Case Manager bearer token")
            authenticated = True

        if is_write and not authenticated:
            return _json_error(401, "Case Manager writes require bearer authentication")

        if not authenticated:
            if requested_clearance not in {None, "public"}:
                return _json_error(401, "Authentication is required for non-public case data")
            _set_header(request, "x-case-clearance", "public")
            return await call_next(request)

        effective_clearance = requested_clearance or principal.clearance
        if _VISIBILITY_RANK[effective_clearance] > _VISIBILITY_RANK[principal.clearance]:
            return _json_error(
                403,
                "Requested Case Manager clearance exceeds the authenticated principal",
            )

        presented_actor = request.headers.get("x-case-actor")
        if presented_actor is not None and presented_actor != principal.actor:
            return _json_error(403, "X-Case-Actor does not match the authenticated principal")

        _set_header(request, "x-case-clearance", effective_clearance)
        if is_write:
            _set_header(request, "x-case-actor", principal.actor)
        return await call_next(request)
