"""Promotion guard — blocks promotion of a non-validated build to master.

Issue #86: governance artifacts + promotion guard. The guard inspects the
machine-readable project state and refuses promotion to the master/main
branch when a validated production tier is claimed without supporting
evidence.

Diagnostic development is intentionally unrestricted: when the claimed
status is a known diagnostic tier, the guard reports ELIGIBLE so ordinary
pull requests to main are never blocked.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

CURRENT_STATUS = Path("reports/current_status.json")
PRODUCTION_STATUS = Path("data/exports/production_status.json")

# Known diagnostic / pre-production tiers (see docs/PRODUCTION_GATES.md).
# A claimed status outside this set is treated as a promotion claim and must
# carry validation evidence before promotion to master is allowed.
DIAGNOSTIC_TIERS = frozenset(
    {
        "NON_PRODUCTION_DIAGNOSTIC",
        "PARTIAL_AVAILABLE_SOURCE_COVERAGE",
        "COMPLETE_AVAILABLE_SOURCE_COVERAGE",
    }
)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _safe_int(value: Any) -> int:
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return 0


def evaluate_promotion(
    status_payload: dict[str, Any],
    production_payload: dict[str, Any],
) -> dict[str, Any]:
    """Decide whether the current build may be promoted to master.

    A promotion claim is any ``production_status`` outside ``DIAGNOSTIC_TIERS``.
    When a claim is present, every evidence condition must hold; otherwise the
    build is ELIGIBLE because no production assertion is being made.
    """
    claimed = str(status_payload.get("production_status") or "NON_PRODUCTION_DIAGNOSTIC")

    if claimed in DIAGNOSTIC_TIERS:
        return {
            "claimed_status": claimed,
            "promotion_claimed": False,
            "eligible": True,
            "unmet_conditions": [],
            "message": (
                f"No promotion claimed (production_status={claimed}); "
                "diagnostic development is unrestricted."
            ),
        }

    unmet: list[str] = []

    if status_payload.get("pause_lock_active") is True:
        unmet.append("pause_lock_active is true — release the pause lock before promotion")

    last_tests = status_payload.get("last_tests") or {}
    if last_tests.get("status") != "GREEN" or _safe_int(last_tests.get("failed")) != 0:
        unmet.append("last_tests is not GREEN with 0 failures in reports/current_status.json")

    audit = status_payload.get("secrets_audit") or {}
    if _safe_int(audit.get("findings")) != 0 or audit.get("real_keys_in_repo") is True:
        unmet.append("secrets_audit reports findings or real keys present in the repo")

    if not production_payload:
        unmet.append(
            "data/exports/production_status.json missing — "
            "run scripts/run_production_status_gate.py"
        )
    else:
        gate_status = production_payload.get("production_status")
        if gate_status == "NON_PRODUCTION_DIAGNOSTIC":
            unmet.append("production-status gate evaluates to NON_PRODUCTION_DIAGNOSTIC")
        if _safe_int(production_payload.get("blocker_count")) != 0:
            unmet.append(
                f"production-status gate reports {production_payload.get('blocker_count')} "
                "open blocker(s)"
            )

    eligible = not unmet
    if eligible:
        message = f"Promotion to master ELIGIBLE — claimed tier {claimed} is fully evidenced."
    else:
        message = (
            f"Promotion to master BLOCKED — claimed tier {claimed} lacks "
            f"{len(unmet)} required evidence condition(s)."
        )

    return {
        "claimed_status": claimed,
        "promotion_claimed": True,
        "eligible": eligible,
        "unmet_conditions": unmet,
        "message": message,
    }


def run_guard(root: Path) -> dict[str, Any]:
    """Load project state from ``root`` and evaluate the promotion guard."""
    root = Path(root)
    status_payload = _read_json(root / CURRENT_STATUS)
    production_payload = _read_json(root / PRODUCTION_STATUS)
    return evaluate_promotion(status_payload, production_payload)
