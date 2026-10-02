#!/usr/bin/env python3
"""Generate the offline dashboard snapshot using concrete route arguments."""

from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from server.backend import main as backend  # noqa: E402
from server.backend import campaign_finance as campaign  # noqa: E402

ENDPOINTS = {
    "/health": backend.health,
    "/contracts": backend.contracts,
    "/contracts?status=ACTIVE": lambda: backend.contracts(status="ACTIVE"),
    "/entities": backend.entities,
    "/edges": backend.edges,
    "/municipalities": backend.municipalities,
    "/stats": backend.stats,
    "/campaign-finance/summary": campaign.campaign_finance_summary,
    "/campaign-finance/contributions": lambda: campaign.campaign_finance_contributions(
        limit=500, offset=0
    ),
    "/campaign-finance/entities": lambda: campaign.campaign_finance_entities(limit=1000),
    "/campaign-finance/reports": lambda: campaign.campaign_finance_reports(limit=1000),
}

OUT = _ROOT / "dashboard" / "src" / "lib" / "snapshot.json"


def main() -> None:
    snapshot = {path: fn() for path, fn in ENDPOINTS.items()}
    OUT.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n")
    counts = {
        path: len(value.get("rows", []))
        if isinstance(value, dict) and "rows" in value
        else len(value)
        if isinstance(value, list)
        else 1
        for path, value in snapshot.items()
    }
    print(f"wrote {OUT.relative_to(Path.cwd())}  {counts}")


if __name__ == "__main__":
    main()
