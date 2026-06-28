"""Route interpretive issues to a review queue instead of auto-correcting them."""

from __future__ import annotations

import json
from pathlib import Path

from .models import MaintenanceFinding

REVIEW_QUEUE_RELPATH = "reports/maintenance/review_queue.json"


def write_review_queue(repo: str, findings: list[MaintenanceFinding], root: Path) -> Path:
    items = [
        f.to_dict()
        for f in findings
        if f.action == "quarantined" or f.severity in ("error", "critical")
    ]
    out = root / REVIEW_QUEUE_RELPATH
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps({"repo": repo, "count": len(items), "items": items}, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return out
