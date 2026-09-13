#!/usr/bin/env python3
"""Promote one verified leaderboard snapshot into a bounded PASS artifact.

Certification is separate from ranking. Adapters may remain PROVISIONAL while a
specific frozen snapshot is promoted only after the declared production scope
closes its identity, currency, accounting, source and runtime gates. The source
snapshot is never modified in place.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from server.backend.leaderboard_history import snapshot_sha256, verify_snapshot

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCOPE = ROOT / "data" / "manifests" / "leaderboards" / "leaderboard_certification_scope_v1.json"
DEFAULT_OUT_DIR = ROOT / "data" / "manifests" / "leaderboards" / "certified_snapshots"


def _is_sha(value: object, length: int) -> bool:
    text = str(value or "")
    return len(text) == length and all(ch in "0123456789abcdef" for ch in text.lower())


def _load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SystemExit(f"certification blocked: missing file {path}") from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(f"certification blocked: invalid JSON {path}") from exc


def _category_scope(scope: dict[str, Any], category_id: str) -> dict[str, Any]:
    for item in scope.get("includedCategories") or []:
        if item.get("categoryId") == category_id:
            return item
    raise SystemExit(f"certification blocked: category outside production scope: {category_id}")


def certification_errors(snapshot: dict[str, Any], scope: dict[str, Any]) -> list[str]:
    errors = [f"snapshot.{item}" for item in verify_snapshot(snapshot)]
    if scope.get("schemaVersion") != "moneysweep.leaderboard-certification-scope/v1":
        errors.append("scope.schemaVersion")
    if scope.get("rankingContractVersion") != snapshot.get("rankingVersion"):
        errors.append("scope.rankingContractVersion")

    category_id = str(snapshot.get("categoryId") or "")
    try:
        category = _category_scope(scope, category_id)
    except SystemExit:
        errors.append("scope.category")
        return sorted(set(errors))

    if snapshot.get("metricType") != category.get("metricType"):
        errors.append("metricType")
    expected_currencies = sorted(str(item) for item in category.get("currencyUniverse") or [])
    observed_currencies = sorted(str(item) for item in snapshot.get("currencies") or [])
    if observed_currencies != expected_currencies:
        errors.append("currencies")

    rows = snapshot.get("rows") or []
    if snapshot.get("candidateCount") != len(rows):
        errors.append("candidateCount")
    expected_identity = str(category.get("identityNamespace") or "")
    for row in rows:
        if row.get("entityResolutionState") != expected_identity:
            errors.append("row.entityResolutionState")
        if row.get("metricType") != category.get("metricType"):
            errors.append("row.metricType")
        if str(row.get("currency") or "") not in expected_currencies:
            errors.append("row.currency")
        if not str(row.get("entityId") or ""):
            errors.append("row.entityId")

    accounting = snapshot.get("accounting") or {}
    required = category.get("requiredAccounting") or {}
    for key, expected in required.items():
        if accounting.get(key) != expected:
            errors.append(f"accounting.{key}")

    runtime = snapshot.get("runtimeManifest") or {}
    if runtime.get("state") != "FROZEN":
        errors.append("runtimeManifest.state")
    if not _is_sha(runtime.get("producerCommit"), 40):
        errors.append("runtimeManifest.producerCommit")
    runtime_files = runtime.get("files")
    if not isinstance(runtime_files, list) or not runtime_files:
        errors.append("runtimeManifest.files")
    else:
        for item in runtime_files:
            if item.get("state") == "MISSING" or not _is_sha(item.get("sha256"), 64):
                errors.append("runtimeManifest.fileHash")
                break

    manifestations = snapshot.get("sourceManifestations")
    if not isinstance(manifestations, list) or not manifestations:
        errors.append("sourceManifestations")
    else:
        for item in manifestations:
            if not str(item.get("path") or "") or not _is_sha(item.get("sha256"), 64):
                errors.append("sourceManifestations.hash")
                break

    if snapshot.get("certificationState") not in {"PROVISIONAL", "PASS"}:
        errors.append("certificationState.input")
    return sorted(set(errors))


def certify(snapshot: dict[str, Any], scope: dict[str, Any], *, certified_at: str) -> dict[str, Any]:
    errors = certification_errors(snapshot, scope)
    if errors:
        raise ValueError(";".join(errors))
    source_hash = snapshot["snapshotSha256"]
    certified = dict(snapshot)
    certified["certificationState"] = "PASS"
    certified["certification"] = {
        "state": "PASS",
        "scopeId": scope["scopeId"],
        "certifiedAt": certified_at,
        "sourceSnapshotSha256": source_hash,
        "zeroMaterialUnresolvedResidue": True,
        "ciExecutionPolicy": scope.get("ciExecutionPolicy") or {},
    }
    certified["snapshotSha256"] = snapshot_sha256(certified)
    post_errors = verify_snapshot(certified)
    if post_errors:
        raise ValueError("certified snapshot verification failed: " + ",".join(post_errors))
    return certified


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("--scope", type=Path, default=DEFAULT_SCOPE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--certified-at")
    args = parser.parse_args()

    snapshot = _load_json(args.snapshot)
    scope = _load_json(args.scope)
    certified_at = args.certified_at or datetime.now(tz=UTC).replace(microsecond=0).isoformat()
    try:
        certified = certify(snapshot, scope, certified_at=certified_at)
    except ValueError as exc:
        raise SystemExit(f"certification blocked: {exc}") from exc

    args.output_dir.mkdir(parents=True, exist_ok=True)
    safe_id = str(certified["snapshotId"]).replace(":", "_").replace("/", "_")
    path = args.output_dir / f"{safe_id}.json"
    if path.exists():
        existing = _load_json(path)
        if existing != certified:
            raise SystemExit(f"refusing to overwrite non-identical certified snapshot: {path}")
        print(json.dumps({"state": "PASS", "idempotent": True, "path": str(path), "snapshotSha256": certified["snapshotSha256"]}, indent=2))
        return 0
    path.write_text(json.dumps(certified, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"state": "PASS", "idempotent": False, "path": str(path), "snapshotSha256": certified["snapshotSha256"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
