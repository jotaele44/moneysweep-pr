"""Frozen leaderboard snapshot and rank-delta semantics.

Snapshots are immutable evidence artifacts. Comparisons are permitted only when
category, financial measure, ranking contract, currency/filter universe and
runtime manifestation are equal. Source or runtime changes remain visible in the
comparison receipt rather than being mislabeled as economic activity.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT_DIR = ROOT / "data" / "manifests" / "leaderboards" / "snapshots"


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def snapshot_sha256(snapshot: dict[str, Any]) -> str:
    payload = dict(snapshot)
    payload.pop("snapshotSha256", None)
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def make_snapshot(
    ranking: dict[str, Any],
    *,
    captured_at: str,
    snapshot_id: str,
    runtime_manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Convert a complete ranking result (limit=None) into an immutable snapshot."""
    if ranking.get("topN") is not None:
        raise ValueError("snapshot source ranking must contain the complete candidate universe")
    accounting = ranking.get("accounting") or {}
    if not accounting.get("arithmeticClosed"):
        raise ValueError("ranking accounting must close before snapshot materialization")
    snapshot = {
        "schemaVersion": "moneysweep.leaderboard-snapshot/v1.1",
        "snapshotId": snapshot_id,
        "capturedAt": captured_at,
        "categoryId": ranking["categoryId"],
        "metricType": ranking["metricType"],
        "rankingVersion": ranking["rankingVersion"],
        "filters": ranking.get("filters") or {},
        "currencies": ranking.get("currencies") or [],
        "candidateCount": ranking.get("candidateCount", len(ranking.get("rows") or [])),
        "accounting": accounting,
        "rows": ranking.get("rows") or [],
        "sourceManifestations": ranking.get("sourceManifestations") or [],
        "runtimeManifest": runtime_manifest or {"state": "UNSPECIFIED"},
        "methodology": ranking.get("methodology") or {},
        "certificationState": ranking.get("certificationState"),
    }
    snapshot["snapshotSha256"] = snapshot_sha256(snapshot)
    return snapshot


def verify_snapshot(snapshot: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if snapshot.get("schemaVersion") != "moneysweep.leaderboard-snapshot/v1.1":
        errors.append("schema_version")
    expected = snapshot.get("snapshotSha256")
    if not expected or expected != snapshot_sha256(snapshot):
        errors.append("snapshot_sha256")
    rows = snapshot.get("rows")
    if not isinstance(rows, list):
        errors.append("rows")
        rows = []
    ids = [str(row.get("entityId") or "") for row in rows]
    if any(not value for value in ids):
        errors.append("blank_entity_id")
    if len(ids) != len(set(ids)):
        errors.append("duplicate_entity_id")
    accounting = snapshot.get("accounting") or {}
    if accounting.get("arithmeticClosed") is not True:
        errors.append("arithmetic_not_closed")
    runtime_manifest = snapshot.get("runtimeManifest")
    if not isinstance(runtime_manifest, dict) or not runtime_manifest:
        errors.append("runtime_manifest")
    return errors


def list_snapshots(category: str | None = None) -> list[dict[str, Any]]:
    if not SNAPSHOT_DIR.exists():
        return []
    rows: list[dict[str, Any]] = []
    for path in sorted(SNAPSHOT_DIR.glob("*.json")):
        try:
            snapshot = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        errors = verify_snapshot(snapshot)
        if errors:
            continue
        if category and snapshot.get("categoryId") != category:
            continue
        rows.append(snapshot)
    rows.sort(key=lambda row: (str(row.get("capturedAt") or ""), str(row.get("snapshotId") or "")))
    return rows


def _comparison_key(snapshot: dict[str, Any]) -> tuple[str, str, str, str, str]:
    return (
        str(snapshot.get("categoryId") or ""),
        str(snapshot.get("metricType") or ""),
        str(snapshot.get("rankingVersion") or ""),
        _canonical_json(snapshot.get("filters") or {}),
        _canonical_json(snapshot.get("currencies") or []),
    )


def _runtime_key(snapshot: dict[str, Any]) -> str:
    return _canonical_json(snapshot.get("runtimeManifest") or {})


def compare(prior: dict[str, Any], current: dict[str, Any], *, limit: int = 10) -> dict[str, Any]:
    prior_errors = verify_snapshot(prior)
    current_errors = verify_snapshot(current)
    if prior_errors or current_errors:
        return {
            "certificationState": "UNRESOLVED",
            "movementState": "UNRESOLVED_INVALID_SNAPSHOT",
            "priorErrors": prior_errors,
            "currentErrors": current_errors,
            "rows": [],
        }
    if _comparison_key(prior) != _comparison_key(current):
        return {
            "certificationState": "UNRESOLVED",
            "movementState": "UNRESOLVED_NONCOMPARABLE_SNAPSHOTS",
            "reason": "category/measure/ranking-version/filter/currency universe differs",
            "rows": [],
        }

    old = {row["entityId"]: row for row in prior["rows"]}
    new = {row["entityId"]: row for row in current["rows"]}
    entity_ids = sorted(set(old) | set(new))
    deltas: list[dict[str, Any]] = []
    for entity_id in entity_ids:
        before = old.get(entity_id)
        after = new.get(entity_id)
        if before is None:
            state = "NEW"
            prior_rank = None
            current_rank = after.get("rank")
            rank_delta = None
            value_delta = after.get("metricValue")
        elif after is None:
            state = "EXITED"
            prior_rank = before.get("rank")
            current_rank = None
            rank_delta = None
            value_delta = -float(before.get("metricValue") or 0)
        else:
            prior_rank = before.get("rank")
            current_rank = after.get("rank")
            rank_delta = (
                int(prior_rank) - int(current_rank)
                if prior_rank is not None and current_rank is not None
                else None
            )
            value_delta = float(after.get("metricValue") or 0) - float(before.get("metricValue") or 0)
            if rank_delta and rank_delta > 0:
                state = "UP"
            elif rank_delta and rank_delta < 0:
                state = "DOWN"
            else:
                state = "UNCHANGED"
        display = (after or before or {}).get("entityDisplayName") or entity_id
        deltas.append(
            {
                "entityId": entity_id,
                "entityDisplayName": display,
                "priorRank": prior_rank,
                "currentRank": current_rank,
                "rankDelta": rank_delta,
                "valueDelta": value_delta,
                "movementState": state,
            }
        )

    movers = [row for row in deltas if row["movementState"] != "UNCHANGED"]
    movers.sort(
        key=lambda row: (
            -abs(int(row["rankDelta"] or 0)),
            -abs(float(row["valueDelta"] or 0)),
            row["entityId"],
        )
    )
    prior_manifest = {item.get("path"): item.get("sha256") for item in prior.get("sourceManifestations") or []}
    current_manifest = {item.get("path"): item.get("sha256") for item in current.get("sourceManifestations") or []}
    source_changed = prior_manifest != current_manifest
    runtime_changed = _runtime_key(prior) != _runtime_key(current)
    runtime_unspecified = (
        (prior.get("runtimeManifest") or {}).get("state") == "UNSPECIFIED"
        or (current.get("runtimeManifest") or {}).get("state") == "UNSPECIFIED"
    )
    inference_allowed = not source_changed and not runtime_changed and not runtime_unspecified
    if source_changed and runtime_changed:
        reason = "source and runtime manifestations changed; movement is a dataset/runtime delta and must not be labeled economic activity"
    elif source_changed:
        reason = "source manifestations changed; movement is a dataset delta and must not be labeled economic activity"
    elif runtime_changed:
        reason = "runtime manifestation changed; movement may reflect code/dependency behavior and must not be labeled economic activity"
    elif runtime_unspecified:
        reason = "runtime manifestation is unspecified; economic-change inference is fail-closed"
    else:
        reason = "source and runtime manifestations are identical; rank/value movement is comparable within the frozen contract"
    return {
        "categoryId": current["categoryId"],
        "metricType": current["metricType"],
        "certificationState": "PROVISIONAL",
        "movementState": "COMPARABLE_SNAPSHOT_DELTA",
        "priorSnapshotId": prior["snapshotId"],
        "currentSnapshotId": current["snapshotId"],
        "sourceManifestationChanged": source_changed,
        "runtimeManifestationChanged": runtime_changed,
        "runtimeManifestationSpecified": not runtime_unspecified,
        "economicChangeInferenceAllowed": inference_allowed,
        "reason": reason,
        "rows": movers[:limit],
        "movementCounts": {
            state: sum(1 for row in deltas if row["movementState"] == state)
            for state in ("NEW", "EXITED", "UP", "DOWN", "UNCHANGED")
        },
    }


def latest_movers(category: str, *, limit: int = 10) -> dict[str, Any]:
    snapshots = list_snapshots(category)
    if len(snapshots) < 2:
        return {
            "categoryId": category,
            "certificationState": "OPEN",
            "movementState": "OPEN_NO_PRIOR_SNAPSHOT",
            "reason": "At least two valid frozen comparable snapshots are required.",
            "snapshotCount": len(snapshots),
            "rows": [],
            "limit": limit,
        }
    current = snapshots[-1]
    for prior in reversed(snapshots[:-1]):
        if _comparison_key(prior) == _comparison_key(current):
            return compare(prior, current, limit=limit)
    return {
        "categoryId": category,
        "certificationState": "UNRESOLVED",
        "movementState": "UNRESOLVED_NO_COMPARABLE_PRIOR_SNAPSHOT",
        "reason": "Snapshots exist, but none share the current category/measure/version/filter/currency universe.",
        "snapshotCount": len(snapshots),
        "rows": [],
        "limit": limit,
    }
