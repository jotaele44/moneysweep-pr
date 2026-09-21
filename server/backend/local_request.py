"""Shared loopback trust boundary for locally-scoped backend routes.

Extracted from ``api_keys.py`` so the API-key store and the Case Manager share
one implementation rather than two drifting copies. The check is deliberately
narrow: it answers "did this request originate on this machine", nothing more.
It is a boundary, not an identity — callers that need to know *who* is asking
must layer authentication on top (see ``case_manager_auth.py``).
"""

from __future__ import annotations

import re

from fastapi import HTTPException, Request

_LOCAL_ORIGIN = re.compile(r"^https?://(localhost|127\.0\.0\.1|\[::1\])(?::\d+)?$")
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1"})


def require_loopback(request: Request, *, detail: str = "request requires loopback") -> None:
    """Reject any request that did not originate on the loopback interface.

    Raises ``HTTPException`` 403 when the peer address is not loopback, or when
    a browser supplied a cross-origin ``Origin`` header (which would indicate a
    page on another site driving the local service).
    """
    client_host = request.client.host if request.client else ""
    if client_host not in _LOOPBACK_HOSTS:
        raise HTTPException(status_code=403, detail=detail)
    origin = request.headers.get("origin")
    if origin and not _LOCAL_ORIGIN.fullmatch(origin):
        raise HTTPException(status_code=403, detail="untrusted request origin")
