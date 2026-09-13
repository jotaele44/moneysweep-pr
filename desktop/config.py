"""Desktop-wrapper configuration for this repo.

The desktop/ folder is a shared federation template; only this file differs
between repos.
"""

from __future__ import annotations

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

# Health endpoint used to detect that the backend is up.
HEALTH_PATH = "/health"
