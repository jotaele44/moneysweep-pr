"""Deterministic provenance for the leaderboard certification/release runtime.

This manifest is intentionally separate from the ranking runtime manifestation.
It binds the code and immutable contracts that certify, package, and replay a
ranking release, while excluding mutable decision artifacts such as the PASS
receipt and release manifest themselves.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CERTIFICATION_RUNTIME_FILES = [
    ROOT / "scripts" / "leaderboard_release_provenance.py",
    ROOT / "scripts" / "materialize_leaderboard_snapshot.py",
    ROOT / "scripts" / "certify_leaderboard_snapshot.py",
    ROOT / "scripts" / "materialize_leaderboard_git_snapshot.py",
    ROOT / "scripts" / "finalize_leaderboard_release.py",
    ROOT / "scripts" / "export_leaderboard_package.py",
    ROOT / "schemas" / "leaderboard_export_package.schema.json",
    ROOT / "data" / "manifests" / "leaderboards" / "leaderboard_certification_scope_v1.json",
    ROOT / "data" / "manifests" / "leaderboards" / "debt_history_source_refs_v1.json",
]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def certification_runtime_manifest() -> dict[str, Any]:
    files: list[dict[str, Any]] = []
    state = "FROZEN"
    for path in CERTIFICATION_RUNTIME_FILES:
        relative = str(path.relative_to(ROOT))
        if not path.exists():
            files.append({"path": relative, "state": "MISSING"})
            state = "INCOMPLETE"
            continue
        files.append(
            {
                "path": relative,
                "bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
        )
    return {
        "schemaVersion": "moneysweep.leaderboard-certification-runtime/v1",
        "state": state,
        "files": files,
    }


def certification_runtime_sha256(manifest: dict[str, Any] | None = None) -> str:
    value = manifest if manifest is not None else certification_runtime_manifest()
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def validate_certification_runtime(manifest: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if manifest.get("schemaVersion") != "moneysweep.leaderboard-certification-runtime/v1":
        errors.append("schemaVersion")
    if manifest.get("state") != "FROZEN":
        errors.append("state")
    files = manifest.get("files")
    if not isinstance(files, list) or len(files) != len(CERTIFICATION_RUNTIME_FILES):
        errors.append("files")
        files = files if isinstance(files, list) else []
    seen: set[str] = set()
    for item in files:
        path = str(item.get("path") or "")
        digest = str(item.get("sha256") or "")
        if not path or path in seen:
            errors.append("file.path")
        seen.add(path)
        if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
            errors.append("file.sha256")
        if not isinstance(item.get("bytes"), int) or item.get("bytes", -1) < 0:
            errors.append("file.bytes")
    return sorted(set(errors))
