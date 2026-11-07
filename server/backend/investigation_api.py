"""Read-only research-lens contract; no case writes or evidence promotion."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from fastapi import APIRouter, HTTPException

from moneysweep.investigation.lenses import summarize_registry

REGISTRY_PATH = Path(__file__).resolve().parents[2] / "registry/investigation_lenses_v1.json"
router = APIRouter(prefix="/investigation", tags=["investigation"])


@router.get("/lenses")
def research_lenses() -> dict:
    """Return the validated contract and separate implementation/coverage states."""
    try:
        raw = REGISTRY_PATH.read_bytes()
        registry = json.loads(raw)
        summary = summarize_registry(registry)
    except (OSError, ValueError, TypeError) as exc:
        raise HTTPException(503, "research lens registry unavailable or invalid") from exc
    return {
        "registry": registry,
        "summary": summary,
        "provenance": {
            "path": "registry/investigation_lenses_v1.json",
            "sha256": hashlib.sha256(raw).hexdigest(),
            "source_revision": registry["source_revision"],
        },
    }
