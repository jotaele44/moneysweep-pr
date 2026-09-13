"""Standalone Case Manager Phase 1 FastAPI application.

This app is intentionally separate from the canonical CSV dashboard read service. It has no
route capable of changing canonical evidence.
"""

from fastapi import FastAPI, HTTPException

from . import case_manager_api
from .case_manager_api import router

app = FastAPI(
    title="MoneySweep Case Manager API",
    version="0.12.0",
    description=(
        "Command-oriented investigative case service. Canonical evidence is read by identifier "
        "only; generic PATCH and DELETE operations are intentionally absent."
    ),
)
app.include_router(router)


@app.get("/health")
def health() -> dict[str, str]:
    # Mirrors server.backend.main's /health: a real liveness check against this
    # service's actual dependency (the SQLite case database), not an
    # unconditional 200 -- _services() also applies the schema migration on
    # first call, so this also verifies startup succeeded.
    try:
        case_manager_api._services()
        case_manager_api._repository.connection.execute("SELECT 1").fetchone()
    except Exception as exc:
        raise HTTPException(500, "case database unavailable") from exc
    return {"status": "ok", "service": "case-manager-phase-1"}
