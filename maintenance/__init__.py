"""Deterministic, audit-first maintenance/audit layer for moneysweep-pr (vendored).

The shared module set — models, state, detect, corrections, quarantine, report —
is generic; ``adapters/local.py`` holds the repo-specific checks. Run via
``python3 scripts/run_maintenance.py --repo moneysweep-pr --mode audit``.
"""

from __future__ import annotations

from .models import MAINTENANCE_VERSION, MaintenanceFinding, MaintenanceReport
from .report import REPORT_RELPATH
from .runner import run_maintenance

__all__ = [
    "MAINTENANCE_VERSION",
    "MaintenanceFinding",
    "MaintenanceReport",
    "REPORT_RELPATH",
    "run_maintenance",
]
