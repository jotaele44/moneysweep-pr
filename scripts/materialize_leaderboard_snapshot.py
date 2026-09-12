#!/usr/bin/env python3
"""Materialize one complete financial leaderboard snapshot.

The script never downloads data. It reuses the exact local/canonical source
manifestations already mounted in MoneySweep, computes the complete candidate
universe, freezes the executable/runtime manifestation, verifies accounting
closure, and writes an immutable snapshot whose SHA-256 covers the canonical
JSON payload.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from server.backend.leaderboard_history import SNAPSHOT_DIR, make_snapshot, verify_snapshot
from server.backend.main import DATA
from server.backend.leaderboards import build_ranking

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_FILES = [
    ROOT / "config" / "financial_category_ontology.json",
    ROOT / "server" / "backend" / "leaderboards.py",
    ROOT / "server" / "backend" / "leaderboard_adapters.py",
    ROOT / "server" / "backend" / "leaderboard_history.py",
    ROOT / "server" / "backend" / "leaderboard_investigation.py",
    ROOT / "server" / "backend" / "leaderboard_entities.py",
    ROOT / "data" / "manifests" / "leaderboards" / "leaderboard_release_contract_v1.json",
]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _package_version(name: str) -> str | None:
    try:
        return version(name)
    except PackageNotFoundError:
        return None


def _git_head() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return "UNRESOLVED"
    value = result.stdout.strip().lower()
    if len(value) == 40 and all(ch in "0123456789abcdef" for ch in value):
        return value
    return "UNRESOLVED"


def _runtime_manifest() -> dict:
    files = []
    for path in RUNTIME_FILES:
        if not path.exists():
            files.append({"path": str(path.relative_to(ROOT)), "state": "MISSING"})
            continue
        files.append(
            {
                "path": str(path.relative_to(ROOT)),
                "bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
        )
    return {
        "state": "FROZEN",
        "producerCommit": _git_head(),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "packages": {
            "fastapi": _package_version("fastapi"),
            "pandas": _package_version("pandas"),
            "pydantic": _package_version("pydantic"),
        },
        "files": files,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--category", required=True)
    parser.add_argument("--snapshot-id")
    parser.add_argument("--captured-at")
    parser.add_argument("--start-year", type=int)
    parser.add_argument("--end-year", type=int)
    parser.add_argument("--municipality")
    parser.add_argument("--entity-type")
    parser.add_argument("--currency")
    parser.add_argument("--output-dir", type=Path, default=SNAPSHOT_DIR)
    args = parser.parse_args()

    captured_at = args.captured_at or datetime.now(tz=UTC).replace(microsecond=0).isoformat()
    safe_stamp = captured_at.replace(":", "").replace("+00:00", "Z").replace("-", "")
    snapshot_id = args.snapshot_id or f"{args.category}:{safe_stamp}"

    ranking = build_ranking(
        DATA,
        category=args.category,
        limit=None,
        start_year=args.start_year,
        end_year=args.end_year,
        municipality=args.municipality,
        entity_type=args.entity_type,
        currency=args.currency,
    )
    if ranking.get("certificationState") not in {"PASS", "PROVISIONAL"}:
        raise SystemExit(
            f"snapshot blocked: ranking state={ranking.get('certificationState')} reason={ranking.get('reason')}"
        )
    runtime_manifest = _runtime_manifest()
    if runtime_manifest["producerCommit"] == "UNRESOLVED":
        raise SystemExit("snapshot blocked: exact producer git commit could not be resolved")
    if any(item.get("state") == "MISSING" for item in runtime_manifest["files"]):
        raise SystemExit("snapshot blocked: required runtime/release manifestation file is missing")

    snapshot = make_snapshot(
        ranking,
        captured_at=captured_at,
        snapshot_id=snapshot_id,
        runtime_manifest=runtime_manifest,
    )
    errors = verify_snapshot(snapshot)
    if errors:
        raise SystemExit(f"snapshot verification failed: {errors}")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    path = args.output_dir / f"{safe_stamp}_{args.category}.json"
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
        if existing != snapshot:
            raise SystemExit(f"refusing to overwrite non-identical snapshot: {path}")
        print(json.dumps({"state": "PASS", "path": str(path), "snapshotSha256": snapshot["snapshotSha256"], "idempotent": True}, indent=2))
        return 0

    path.write_text(json.dumps(snapshot, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"state": "PASS", "path": str(path), "snapshotSha256": snapshot["snapshotSha256"], "idempotent": False}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
