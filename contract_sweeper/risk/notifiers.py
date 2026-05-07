"""Notification helpers for risk signals."""

from __future__ import annotations

import os
from typing import Any

import pandas as pd


def external_notifications_enabled(env: dict[str, str] | None = None) -> bool:
    """Return true only when external delivery is explicitly enabled."""

    values = env if env is not None else os.environ
    return values.get("CONTRACT_SWEEPER_ENABLE_EXTERNAL_NOTIFICATIONS", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }


def notify_alerts(alerts: pd.DataFrame, env: dict[str, str] | None = None) -> dict[str, Any]:
    """Return a local notification summary unless outbound delivery is enabled."""

    if not external_notifications_enabled(env):
        return {
            "mode": "local_only",
            "external_notifications_enabled": False,
            "alerts_observed": int(len(alerts)),
            "notifications_sent": 0,
        }

    return {
        "mode": "external_requested_not_configured",
        "external_notifications_enabled": True,
        "alerts_observed": int(len(alerts)),
        "notifications_sent": 0,
    }
