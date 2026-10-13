#!/usr/bin/env python3
"""Replay a canonical leaderboard against an exact historical Git manifestation.

This is a source-history materializer, not synthetic history. It reads canonical
CSV bytes directly from an existing Git commit with ``git show`` and executes the
*current* leaderboard contract against those frozen bytes. The resulting
snapshot records both the historical source commit and the current runtime
manifestation. Source changes therefore remain visible to the mover engine and
never become automatic claims of economic activity.

Initial bounded support is limited to canonical-source adapters whose required
inputs are fully contained in ``data/canonical_v1``: ``contract_award`` and
``debt_issuance``. Staging-backed adapters are intentionally excluded because a
Git commit alone does not prove that optional external materializations were
present in a comparable universe.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from scripts.materialize_leaderboard_snapshot import _runtime_manifest
from server.backend import leaderboard_adapters as adapters
from server.backend.leaderboard_history import (
    SNAPSHOT_DIR,
    make_snapshot,
    snapshot_sha256,
    verify_snapshot,
)
from server.backend.leaderboards import build_ranking

ROOT = Path(__file__).resolve().parents[1]
CANONICAL_FILES = (
    "contracts.csv",
    "entities.csv",
    "edges.csv",
    "municipalities.csv",
    "debt_instruments.csv",
)
SUPPORTED_CATEGORIES = {"contract_award", "debt_issuance"}


def _resolve_commit(value: str) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", f"{value}^{{commit}}"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise SystemExit(f"historical snapshot blocked: unresolved git commit/ref {value!r}") from exc
    commit = result.stdout.strip().lower()
    if len(commit) != 40 or any(ch not in "0123456789abcdef" for ch in commit):
        raise SystemExit(f"historical snapshot blocked: invalid resolved commit {commit!r}")
    return commit


def _commit_timestamp(commit: str) -> str:
    try:
        result = subprocess.run(
            ["git", "show", "-s", "--format=%cI", commit],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise SystemExit(f"historical snapshot blocked: cannot read commit timestamp {commit}") from exc
    value = result.stdout.strip()
    if not value:
        raise SystemExit(f"historical snapshot blocked: empty commit timestamp {commit}")
    return value


def _git_bytes(commit: str, relative_path: str) -> bytes:
    try:
        result = subprocess.run(
            ["git", "show", f"{commit}:{relative_path}"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            timeout=20,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise SystemExit(
            f"historical snapshot blocked: {relative_path} is not readable at {commit}"
        ) from exc
    return result.stdout


def _read_csv(raw: bytes) -> pd.DataFrame:
    try:
        return pd.read_csv(io.BytesIO(raw), dtype=str, low_memory=False).fillna("")
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def _source_manifest(relative_path: str, raw: bytes, commit: str, committed_at: str) -> dict[str, Any]:
    return {
        "path": relative_path,
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "sourceCommit": commit,
        "sourceCommittedAt": committed_at,
        "manifestationType": "GIT_COMMIT_BLOB",
    }


def _load_historical_data(commit: str) -> tuple[dict[str, pd.DataFrame], dict[str, dict[str, Any]]]:
    committed_at = _commit_timestamp(commit)
    frames: dict[str, pd.DataFrame] = {}
    manifests: dict[str, dict[str, Any]] = {}
    for filename in CANONICAL_FILES:
        relative_path = f"data/canonical_v1/{filename}"
        raw = _git_bytes(commit, relative_path)
        frames[filename.removesuffix(".csv")] = _read_csv(raw)
        manifests[filename] = _source_manifest(relative_path, raw, commit, committed_at)
    return {
        "contracts": frames["contracts"],
        "entities": frames["entities"],
        "edges": frames["edges"],
        "municipalities": frames["municipalities"],
        "debt_instruments": frames["debt_instruments"],
    }, manifests


def _replay_ranking(
    *,
    source_commit: str,
    category: str,
    start_year: int | None,
    end_year: int | None,
    municipality: str | None,
    entity_type: str | None,
    currency: str | None,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    if category not in SUPPORTED_CATEGORIES:
        raise SystemExit(
            "historical snapshot blocked: Git-source replay is bounded to "
            f"{sorted(SUPPORTED_CATEGORIES)}; got {category!r}"
        )
    data, manifests = _load_historical_data(source_commit)

    # debt_issuance reads its canonical debt table through adapters.CANON while
    # contract_award reads the supplied DataFrame. Place exact Git bytes in a
    # temporary canonical directory and override only for this replay.
    original_canon = adapters.CANON
    original_manifest = adapters._manifest
    with tempfile.TemporaryDirectory(prefix="leaderboard-git-replay-", dir=ROOT) as temp_name:
        replay_canon = Path(temp_name)
        for filename in CANONICAL_FILES:
            relative_path = f"data/canonical_v1/{filename}"
            (replay_canon / filename).write_bytes(_git_bytes(source_commit, relative_path))

        def manifest_for(path: Path) -> dict[str, Any]:
            item = manifests.get(path.name)
            if item is None:
                raise RuntimeError(f"historical replay requested undeclared source: {path.name}")
            return dict(item)

        adapters.CANON = replay_canon
        adapters._manifest = manifest_for
        try:
            ranking = build_ranking(
                data,
                category=category,
                limit=None,
                start_year=start_year,
                end_year=end_year,
                municipality=municipality,
                entity_type=entity_type,
                currency=currency,
            )
        finally:
            adapters.CANON = original_canon
            adapters._manifest = original_manifest
    return ranking, manifests


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--category", required=True, choices=sorted(SUPPORTED_CATEGORIES))
    parser.add_argument("--snapshot-id")
    parser.add_argument("--captured-at")
    parser.add_argument("--start-year", type=int)
    parser.add_argument("--end-year", type=int)
    parser.add_argument("--municipality")
    parser.add_argument("--entity-type")
    parser.add_argument("--currency")
    parser.add_argument("--output-dir", type=Path, default=SNAPSHOT_DIR)
    args = parser.parse_args()

    source_commit = _resolve_commit(args.source_commit)
    source_committed_at = _commit_timestamp(source_commit)
    captured_at = args.captured_at or source_committed_at
    safe_stamp = captured_at.replace(":", "").replace("+00:00", "Z").replace("-", "")
    snapshot_id = args.snapshot_id or f"{args.category}:git:{source_commit[:12]}"

    ranking, _manifests = _replay_ranking(
        source_commit=source_commit,
        category=args.category,
        start_year=args.start_year,
        end_year=args.end_year,
        municipality=args.municipality,
        entity_type=args.entity_type,
        currency=args.currency,
    )
    if ranking.get("certificationState") not in {"PASS", "PROVISIONAL"}:
        raise SystemExit(
            f"historical snapshot blocked: ranking state={ranking.get('certificationState')} "
            f"reason={ranking.get('reason')}"
        )

    runtime_manifest = _runtime_manifest()
    if runtime_manifest.get("producerCommit") == "UNRESOLVED":
        raise SystemExit("historical snapshot blocked: current runtime git commit unresolved")
    if any(item.get("state") == "MISSING" for item in runtime_manifest.get("files") or []):
        raise SystemExit("historical snapshot blocked: current runtime manifestation incomplete")

    snapshot = make_snapshot(
        ranking,
        captured_at=captured_at,
        snapshot_id=snapshot_id,
        runtime_manifest=runtime_manifest,
    )
    snapshot["snapshotMode"] = "HISTORICAL_GIT_SOURCE_REPLAY"
    snapshot["sourceVersion"] = {
        "type": "GIT_COMMIT",
        "commit": source_commit,
        "committedAt": source_committed_at,
        "replayedAt": datetime.now(tz=UTC).replace(microsecond=0).isoformat(),
        "economicActivityInference": False,
        "note": "Historical source bytes replayed under the frozen current ranking runtime; source expansion/correction is not automatically economic activity.",
    }
    snapshot["snapshotSha256"] = snapshot_sha256(snapshot)
    errors = verify_snapshot(snapshot)
    if errors:
        raise SystemExit(f"historical snapshot verification failed: {errors}")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    path = args.output_dir / f"{safe_stamp}_{args.category}_{source_commit[:12]}.json"
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
        if existing != snapshot:
            raise SystemExit(f"refusing to overwrite non-identical historical snapshot: {path}")
        print(json.dumps({"state": "PASS", "path": str(path), "snapshotSha256": snapshot["snapshotSha256"], "idempotent": True}, indent=2))
        return 0

    path.write_text(json.dumps(snapshot, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"state": "PASS", "path": str(path), "snapshotSha256": snapshot["snapshotSha256"], "idempotent": False}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
