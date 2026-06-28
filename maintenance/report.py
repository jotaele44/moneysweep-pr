"""Emit the producer's latest maintenance report (reports/maintenance/latest.json)."""

from __future__ import annotations

import json
from pathlib import Path

from .models import MaintenanceReport

REPORT_RELPATH = "reports/maintenance/latest.json"


def write_latest_report(report: MaintenanceReport, root: Path) -> Path:
    out = root / REPORT_RELPATH
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
    return out
