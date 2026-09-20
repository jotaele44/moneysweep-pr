"""FastAPI routes for the pipeline's local API-key store.

Deliberate exception to this backend's read-only-diagnostic framing (see
dashboard/README.md): the pipeline (run_all.py) and this backend are separate
process lifetimes, so a key submitted here can only ever be staged on disk in
the local .env file for the pipeline to pick up on its next manual invocation
— it never starts, feeds, or authorizes a running pipeline. Never returns a
key value; only ever reports set/not-set, per docs/SECRET_HANDLING_POLICY.md.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from server.backend.local_request import require_loopback

router = APIRouter(tags=["api-keys"])


def _require_local_request(request: Request) -> None:
    """Thin alias kept so existing call sites and tests are undisturbed."""
    require_loopback(request, detail="API-key writes require loopback")


class SetKeyRequest(BaseModel):
    value: str


@router.get("/api-keys")
def list_api_keys(request: Request) -> list[dict]:
    from scripts.manage_api_keys import key_status

    _require_local_request(request)
    return key_status()


@router.post("/api-keys/{name}")
def set_api_key(name: str, body: SetKeyRequest, request: Request) -> dict:
    from scripts.manage_api_keys import (
        InvalidKeyValueError,
        UnknownKeyError,
        key_status,
        set_key,
    )

    _require_local_request(request)
    try:
        set_key(name, body.value)
    except UnknownKeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InvalidKeyValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    updated = next(row for row in key_status() if row["name"] == name)
    return {"name": name, "is_set": updated["is_set"]}
