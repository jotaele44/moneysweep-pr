"""Desktop-wrapper configuration for this repo.

The desktop/ folder is a shared federation template; only this file differs
between repos.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# User-facing window title of the desktop app.
APP_TITLE = "MoneySweep"

# Desktop-specific composition root: normal dashboard API + writable workspace
# + offline/API materialization control plane.
APP_IMPORT = "server.backend.desktop_app:app"

# Directory containing the Vite frontend (with package.json).
FRONTEND_DIR = REPO_ROOT / "dashboard"

# Vite build output served by the desktop app.
DIST_DIR = FRONTEND_DIR / "dist"

# Requirement files installed into the private .venv by the developer wrapper.
# The standalone release build installs the same full runtime set before freezing.
REQUIREMENT_FILES = [
    REPO_ROOT / "requirements.txt",
    REPO_ROOT / "server" / "backend" / "requirements.txt",
    REPO_ROOT / "requirements-desktop.txt",
]

# The workspace chosen in Setup & Diagnostics is exported through this variable
# (read by desktop.workspace.workspace_root), and SETUP_ACTION re-bootstraps the
# data tree inside that workspace when Save or Repair is pressed.
DATA_ENV_VAR = "MONEYSWEEP_WORKSPACE_ROOT"
SETUP_ACTION = "desktop.workspace:bootstrap_workspace"

# Health endpoint used to detect that the backend is up.
HEALTH_PATH = "/health"


def _launchpad_status() -> list[dict[str, str]]:
    """Readiness rows for the Launch Pad. Runs before the backend exists, so it
    reads the workspace files directly. desktop/launch.py has already run
    bootstrap_workspace(), which exports MONEYSWEEP_DATA_ROOT.
    """
    data_root = os.environ.get("MONEYSWEEP_DATA_ROOT", "").strip()
    workspace = os.environ.get(DATA_ENV_VAR, "").strip()
    canonical = (Path(data_root) if data_root else REPO_ROOT / "data") / "canonical_v1"

    def rows(name: str) -> int:
        path = canonical / name
        if not path.is_file():
            return 0
        with path.open("rb") as stream:
            return max(sum(1 for line in stream if line.strip()) - 1, 0)  # minus header

    contracts, entities = rows("contracts.csv"), rows("entities.csv")
    runs = (
        sum(1 for _ in (Path(workspace) / "receipts" / "materialization_runs").glob("*"))
        if workspace and (Path(workspace) / "receipts" / "materialization_runs").is_dir()
        else 0
    )
    try:
        production = json.loads(
            (REPO_ROOT / "data" / "exports" / "production_status.json").read_text(encoding="utf-8")
        ).get("production_status", "UNKNOWN")
    except (OSError, ValueError):
        production = "UNKNOWN"
    diagnostic = production != "PRODUCTION"
    return [
        {
            "label": "Canonical tables",
            "value": f"{contracts:,} contracts, {entities:,} entities",
            "status": "pass" if entities else "fail",
            "detail": (
                f"Loaded from {canonical}."
                if entities
                else f"No canonical tables found in {canonical}. Open Setup & "
                "Diagnostics and choose Repair."
            ),
        },
        {
            "label": "Materialization runs",
            "value": f"{runs:,}" if runs else "None yet",
            "status": "pass" if runs else "info",
            "detail": (
                "Receipts from source materialization runs in this workspace."
                if runs
                else "Only the bundled seed tables are present. An Operator can "
                "load real sources from the Data Sources tab."
            ),
        },
        {
            "label": "Release status",
            "value": production.replace("_", " ").title(),
            "status": "info" if diagnostic else "pass",
            "detail": (
                "Diagnostic build: figures are not certified for production use."
                if diagnostic
                else "Production-data release gate passed."
            ),
        },
    ]


# Pre-launch screen shown by the shared runtime (prii_desktop.launchpad).
#
# Operator sets no credential: the API's only guard is its loopback check
# (server/backend/local_request.py), which the desktop window always passes.
# Guest adds a refusal in front of every non-GET route.
LAUNCHPAD = {
    "tagline": "Public-money intelligence for Puerto Rico",
    "summary": (
        "MoneySweep is the federation's public-money producer. It links "
        "Puerto Rico procurement, contractor, lobbying, campaign-finance, debt "
        "and recovery records, and this diagnostic dashboard lets you inspect "
        "those links and load the sources behind them."
    ),
    "highlights": [
        "Contracts and entities",
        "Relationships graph",
        "Campaign finance",
        "Certified ownership",
        "Source materialization",
    ],
    "status": _launchpad_status,
    # The dashboard is one route; its pages are ?tab= values (TABS in
    # dashboard/src/pages/Dashboard.jsx).
    "start_pages": [
        {
            "route": "/?tab=contracts",
            "label": "Contracts",
            "description": "The default view: contract records.",
        },
        {"route": "/?tab=activity", "label": "Activity"},
        {"route": "/?tab=leaderboards", "label": "Top Entities"},
        {"route": "/?tab=entities", "label": "Entities"},
        {"route": "/?tab=government-changes", "label": "Gov Changes"},
        {"route": "/?tab=graph", "label": "Relationships"},
        {"route": "/?tab=municipios", "label": "Municipios"},
        {"route": "/?tab=campaign-finance", "label": "Campaign Finance"},
        {"route": "/?tab=ownership", "label": "Ownership"},
        {
            "route": "/?tab=data-sources",
            "label": "Data Sources",
            "description": "Load offline files and run API materialization (Operator).",
        },
        {
            "route": "/?tab=api-keys",
            "label": "API Keys",
            "description": "Store source API keys (Operator).",
        },
    ],
    "guest": {
        "label": "Guest",
        "description": (
            "Read-only. Browse every tab. Uploading files, running "
            "materialization or audits, and saving or deleting API keys are "
            "refused."
        ),
    },
    "operator": {
        "label": "Operator",
        "description": (
            "Full access from this computer: load source files, run API "
            "materialization and audits, and manage stored API keys."
        ),
    },
    # None of the API's non-GET routes is a pure read (even a materialization
    # dry run writes a receipt), so a guest is allowed none of them.
    "guest_guard": {"allow": []},
    "options": [
        {
            "id": "financials_root",
            "label": "Financial records folder",
            "kind": "text",
            "env": "MONEYSWEEP_FINANCIALS_ROOT",
            "operator_only": True,
            "placeholder": "Folder holding the authorized HUD DRGR source files",
            "help": (
                "Used by the HUD DRGR source audit. Without it the audit looks "
                "in a folder that exists on one development machine only, and "
                "reports every path as unresolved."
            ),
        },
    ],
}
