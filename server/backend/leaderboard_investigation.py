"""Typed investigation signals derived from leaderboard evidence.

Signals are observations and triage aids, not allegations and not identity
claims. No opaque composite risk/suspicion score is produced. Every signal
states the arithmetic/evidence that generated it and preserves source/runtime
change caveats from historical comparisons.
"""

from __future__ import annotations

from typing import Any


def _share(value: float, total: float) -> float | None:
    if total == 0:
        return None
    return value / total


def build_signals(ranking: dict[str, Any], movers: dict[str, Any] | None = None) -> dict[str, Any]:
    rows = ranking.get("rows") or []
    accounting = ranking.get("accounting") or {}
    signals: list[dict[str, Any]] = []

    total = sum(float(row.get("metricValue") or 0) for row in rows)
    if rows and total:
        top = rows[0]
        top5 = rows[:5]
        signals.append(
            {
                "signalType": "TOP_ENTITY_SHARE",
                "state": "COMPUTED",
                "entityId": top.get("entityId"),
                "entityDisplayName": top.get("entityDisplayName"),
                "value": _share(float(top.get("metricValue") or 0), total),
                "denominator": total,
                "measure": ranking.get("metricType"),
                "interpretation": "Descriptive concentration only; it does not imply impropriety.",
            }
        )
        signals.append(
            {
                "signalType": "TOP_5_SHARE",
                "state": "COMPUTED",
                "entityId": None,
                "value": _share(sum(float(row.get("metricValue") or 0) for row in top5), total),
                "denominator": total,
                "measure": ranking.get("metricType"),
                "interpretation": "Descriptive concentration only; compare only within the same bounded ranking universe.",
            }
        )

    unresolved = int(accounting.get("unresolvedRecords") or 0)
    if unresolved:
        signals.append(
            {
                "signalType": "IDENTITY_OR_SEMANTIC_REVIEW_REQUIRED",
                "state": "OPEN",
                "value": unresolved,
                "interpretation": "Records were withheld from aggregation because identity, currency or topology did not close.",
            }
        )
    excluded = int(accounting.get("excludedRecords") or 0)
    if excluded:
        signals.append(
            {
                "signalType": "MISSING_FINANCIAL_VALUE",
                "state": "OPEN",
                "value": excluded,
                "interpretation": "In-scope records lacked the adapter's required financial amount and were not silently treated as zero.",
            }
        )

    if movers:
        source_changed = bool(movers.get("sourceManifestationChanged"))
        runtime_changed = bool(movers.get("runtimeManifestationChanged"))
        inference_allowed = bool(movers.get("economicChangeInferenceAllowed"))
        for movement in movers.get("rows") or []:
            state = movement.get("movementState")
            signal_type = {
                "NEW": "NEW_RANKED_ENTITY",
                "EXITED": "RANKED_ENTITY_EXIT",
                "UP": "RANK_SURGE",
                "DOWN": "RANK_DECLINE",
            }.get(state)
            if not signal_type:
                continue
            signals.append(
                {
                    "signalType": signal_type,
                    "state": "COMPUTED_COMPARABLE_DELTA" if inference_allowed else "COMPUTED_MANIFESTATION_DELTA",
                    "entityId": movement.get("entityId"),
                    "entityDisplayName": movement.get("entityDisplayName"),
                    "priorRank": movement.get("priorRank"),
                    "currentRank": movement.get("currentRank"),
                    "rankDelta": movement.get("rankDelta"),
                    "valueDelta": movement.get("valueDelta"),
                    "economicChangeInferenceAllowed": inference_allowed,
                    "interpretation": (
                        "Source or runtime manifestations changed/are unspecified; treat this as a dataset/change-control signal, not evidence that financial activity occurred in the interval."
                        if not inference_allowed
                        else "Comparable frozen source and runtime manifestations support a rank/value delta observation; substantive causation still requires record-level review."
                    ),
                }
            )
        if source_changed:
            signals.append(
                {
                    "signalType": "SOURCE_MANIFESTATION_CHANGED",
                    "state": "OPEN_ADJUDICATION_REQUIRED",
                    "value": True,
                    "interpretation": "At least one source hash differs between compared snapshots; movement must be adjudicated against source additions, corrections, deletions or transformations.",
                }
            )
        if runtime_changed or movers.get("runtimeManifestationSpecified") is False:
            signals.append(
                {
                    "signalType": "RUNTIME_MANIFESTATION_CHANGED_OR_UNSPECIFIED",
                    "state": "OPEN_ADJUDICATION_REQUIRED",
                    "value": True,
                    "interpretation": "Executable/dependency/runtime equivalence is not proven; economic-change inference remains fail-closed.",
                }
            )

    return {
        "categoryId": ranking.get("categoryId"),
        "metricType": ranking.get("metricType"),
        "certificationState": "AUDIT_ONLY",
        "signalCount": len(signals),
        "signals": signals,
        "rules": {
            "noCompositeSuspicionScore": True,
            "identityPromotion": False,
            "causationClaim": False,
            "sourceChangeGuard": True,
            "runtimeChangeGuard": True,
        },
    }
