"""Committed prebuilt dashboard bundle for the source-checkout desktop wrapper.

The wrapper's first run used to require Node.js and a full ``npm ci`` + ``vite
build``. That made a fresh checkout on a second machine fail whenever Node was
absent, which is the common case for a non-developer. A prebuilt bundle is
therefore committed under ``desktop/prebuilt-dashboard/`` and copied into
``dashboard/dist`` instead.

The bundle lives outside ``dashboard/`` on purpose:

* ``.gitignore`` ignores any directory named ``dist``/``build`` at any depth, so
  the committed copy cannot sit at ``dashboard/dist``;
* ``dashboard/eslint.config.js`` is a rendered federation template that must stay
  byte-identical, so an ``ignores`` entry for the bundle cannot be added there.
  ``eslint .`` runs with ``dashboard`` as its working directory, so keeping the
  bundle outside that tree keeps it out of lint scope with no template change.

Staleness is recorded rather than guessed: the manifest carries a fingerprint of
the dashboard sources the bundle was built from, and a test recomputes it. Only
stdlib is used, and the module stays importable on the Python 3.9 that ships with
the macOS Command Line Tools so the preflight can report a too-old interpreter.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
PREBUILT_DIR = REPO_ROOT / "desktop" / "prebuilt-dashboard"
BUNDLE_DIR = PREBUILT_DIR / "bundle"
MANIFEST_PATH = PREBUILT_DIR / "PREBUILT_MANIFEST.json"
RECEIPT_PATH = REPO_ROOT / "desktop" / ".frontend-source.json"

SCHEMA_VERSION = "moneysweep_prebuilt_dashboard_v1"

# Mirrors .github/workflows/size-guard.yml MAX_BYTES. Asserted by the test suite
# so a font-inlining config change fails in pytest rather than only in CI.
SIZE_GUARD_MAX_BYTES = 5 * 1024 * 1024

# Files whose content changes the built output. Over-inclusion only costs a
# needless rebuild; under-inclusion silently ships a stale dashboard, so when in
# doubt a file belongs here.
FINGERPRINT_FILES: Tuple[str, ...] = (
    "index.html",
    "package.json",
    "package-lock.json",
    "vite.config.js",
    "postcss.config.js",
    "tailwind.config.js",
    "jsconfig.json",
    "components.json",
)
FINGERPRINT_TREES: Tuple[str, ...] = ("src", "public")

# Test-only sources never reach the bundle; excluding them keeps a test-only edit
# from invalidating a bundle that is genuinely current.
_EXCLUDED_SUFFIXES: Tuple[str, ...] = (".test.js", ".test.jsx", ".spec.js", ".spec.jsx")
_EXCLUDED_DIRS: Tuple[str, ...] = ("src/test", "src/__tests__")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_excluded(relative: str) -> bool:
    if relative.endswith(_EXCLUDED_SUFFIXES):
        return True
    return any(relative == d or relative.startswith(d + "/") for d in _EXCLUDED_DIRS)


def iter_fingerprint_inputs(frontend_dir: Path) -> Iterator[Tuple[str, Path]]:
    """Yield ``(relative_posix_path, absolute_path)`` for every fingerprinted file."""
    for name in FINGERPRINT_FILES:
        candidate = frontend_dir / name
        if candidate.is_file():
            yield name, candidate
    for tree in FINGERPRINT_TREES:
        root = frontend_dir / tree
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            relative = path.relative_to(frontend_dir).as_posix()
            if not _is_excluded(relative):
                yield relative, path


def source_fingerprint(frontend_dir: Path) -> str:
    """Digest of the dashboard sources a bundle was built from.

    Deliberately excludes the Node/npm versions: a runner upgrade would otherwise
    invalidate an otherwise-current bundle every time the toolchain moves.
    """
    lines = sorted(
        "{} {}".format(relative, sha256_file(path))
        for relative, path in iter_fingerprint_inputs(frontend_dir)
    )
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def bundle_file_records(bundle_dir: Path) -> List[Dict[str, Any]]:
    records = []
    for path in sorted(bundle_dir.rglob("*"), key=lambda p: p.relative_to(bundle_dir).as_posix()):
        if path.is_file():
            records.append(
                {
                    "path": path.relative_to(bundle_dir).as_posix(),
                    "bytes": path.stat().st_size,
                    "sha256": sha256_file(path),
                }
            )
    return records


def load_manifest(manifest_path: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    path = manifest_path or MANIFEST_PATH
    if not path.is_file():
        return None
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(manifest, dict) or manifest.get("schema_version") != SCHEMA_VERSION:
        return None
    return manifest


def verify_bundle_bytes(manifest: Dict[str, Any], bundle_dir: Path) -> List[str]:
    """Return a list of problems; empty means every recorded file matched."""
    problems = []
    recorded = manifest.get("files")
    if not isinstance(recorded, list) or not recorded:
        return ["manifest records no files"]
    for record in recorded:
        relative = record.get("path")
        path = bundle_dir / relative
        if not path.is_file():
            problems.append("missing: {}".format(relative))
            continue
        if path.stat().st_size != record.get("bytes"):
            problems.append("wrong size: {}".format(relative))
            continue
        if sha256_file(path) != record.get("sha256"):
            problems.append("checksum mismatch: {}".format(relative))
    return problems


def is_stale(manifest: Dict[str, Any], frontend_dir: Path) -> bool:
    return manifest.get("source_fingerprint") != source_fingerprint(frontend_dir)


def _write_receipt(payload: Dict[str, Any]) -> None:
    """Record which frontend path ran so support can tell them apart. Best effort."""
    try:
        RECEIPT_PATH.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", "utf-8")
    except OSError:
        pass


def install_prebuilt_dashboard(
    dist_dir: Path,
    *,
    frontend_dir: Optional[Path] = None,
    bundle_dir: Optional[Path] = None,
    manifest_path: Optional[Path] = None,
    source_build_available: bool = False,
) -> bool:
    """Copy the committed bundle into ``dist_dir``.

    Returns ``True`` when the dashboard is in place and the caller should skip the
    npm build, ``False`` when the caller should build from source instead.

    Corruption raises: serving a half-copied dashboard would be worse than a clear
    failure. Staleness does not raise -- a stale bundle is a maintainer defect that
    the test suite already blocks, and failing an end user for it would recreate
    exactly the dead end this module exists to remove.
    """
    frontend = frontend_dir or (REPO_ROOT / "dashboard")
    bundle = bundle_dir or BUNDLE_DIR
    manifest = load_manifest(manifest_path)
    if manifest is None or not bundle.is_dir():
        return False

    problems = verify_bundle_bytes(manifest, bundle)
    if problems:
        raise SystemExit(
            "Prebuilt dashboard bundle is corrupted ({}).\n"
            "Re-clone the repository, or rebuild with:\n"
            "  python3 scripts/build_prebuilt_dashboard.py --build".format(problems[0])
        )

    stale = is_stale(manifest, frontend)
    if stale and source_build_available:
        return False
    if stale:
        print(
            "Warning: the committed dashboard bundle predates the dashboard sources "
            "in this checkout; using it anyway because Node.js is unavailable.",
            file=sys.stderr,
        )

    if dist_dir.exists():
        shutil.rmtree(dist_dir, ignore_errors=True)
    dist_dir.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(bundle, dist_dir)

    _write_receipt(
        {
            "source": "prebuilt",
            "stale": stale,
            "generated_at": manifest.get("generated_at"),
            "source_fingerprint": manifest.get("source_fingerprint"),
            "file_count": len(manifest.get("files") or []),
        }
    )
    return True


def record_source_build() -> None:
    """Note that the dashboard was built from source rather than the bundle."""
    _write_receipt({"source": "npm", "stale": False})


def build_manifest(
    frontend_dir: Path, bundle_dir: Path, generated_by: Dict[str, Any]
) -> Dict[str, Any]:
    records = bundle_file_records(bundle_dir)
    canonical = json.dumps(records, sort_keys=True, separators=(",", ":")).encode("utf-8")
    generated_at = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "build_command": 'npm ci --no-audit --no-fund && VITE_API_BASE="" npm run build',
        "build_env": {"VITE_API_BASE": ""},
        "generated_by": generated_by,
        "source_fingerprint": source_fingerprint(frontend_dir),
        "bundle_tree_sha256": hashlib.sha256(canonical).hexdigest(),
        "file_count": len(records),
        "total_bytes": sum(record["bytes"] for record in records),
        "files": records,
    }


def environment_description() -> Dict[str, Any]:
    return {
        "node": os.environ.get("PRII_PREBUILT_NODE_VERSION", ""),
        "npm": os.environ.get("PRII_PREBUILT_NPM_VERSION", ""),
        "python": "{}.{}.{}".format(*sys.version_info[:3]),
    }
