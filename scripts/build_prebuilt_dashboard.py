#!/usr/bin/env python3
"""Regenerate the committed prebuilt dashboard bundle.

The bundle lets the source-checkout desktop wrapper start without Node.js. See
``desktop/prebuilt.py`` for the layout and the staleness contract, and
``desktop/README.md`` for when to run this.

    python3 scripts/build_prebuilt_dashboard.py --build       # npm ci + vite build
    python3 scripts/build_prebuilt_dashboard.py --from-dist dashboard/dist
    python3 scripts/build_prebuilt_dashboard.py --check       # verify, change nothing

Logic lives in ``desktop/prebuilt.py``; this file stays a thin CLI so the
coverage floor in pytest.ini is not spent on argument plumbing.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from desktop import prebuilt  # noqa: E402

FRONTEND_DIR = REPO_ROOT / "dashboard"


def _tool_version(executable: str) -> str:
    path = shutil.which(executable)
    if path is None:
        return ""
    try:
        return subprocess.run(
            [path, "--version"], capture_output=True, text=True, timeout=30
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def _npm_build() -> None:
    npm = shutil.which("npm")
    if npm is None:
        raise SystemExit("npm not found. Install Node.js (https://nodejs.org) and retry.")
    env_overrides = {"VITE_API_BASE": ""}
    subprocess.run([npm, "ci", "--no-audit", "--no-fund"], cwd=FRONTEND_DIR, check=True)
    subprocess.run(
        [npm, "run", "build"],
        cwd=FRONTEND_DIR,
        check=True,
        env={**os.environ, **env_overrides},
    )


def _regenerate(dist_dir: Path) -> int:
    index = dist_dir / "index.html"
    if not index.is_file():
        raise SystemExit("No dashboard build found at {} (missing index.html).".format(dist_dir))

    if prebuilt.BUNDLE_DIR.exists():
        shutil.rmtree(prebuilt.BUNDLE_DIR)
    prebuilt.PREBUILT_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copytree(dist_dir, prebuilt.BUNDLE_DIR)

    oversized = [
        record
        for record in prebuilt.bundle_file_records(prebuilt.BUNDLE_DIR)
        if record["bytes"] >= prebuilt.SIZE_GUARD_MAX_BYTES
    ]
    if oversized:
        raise SystemExit(
            "Refusing to commit a bundle that size-guard would reject: {} is {} bytes "
            "(limit {}).".format(
                oversized[0]["path"], oversized[0]["bytes"], prebuilt.SIZE_GUARD_MAX_BYTES
            )
        )

    manifest = prebuilt.build_manifest(
        FRONTEND_DIR,
        prebuilt.BUNDLE_DIR,
        generated_by={"node": _tool_version("node"), "npm": _tool_version("npm")},
    )
    prebuilt.MANIFEST_PATH.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        "Wrote {} files ({:.1f} MB) to {}".format(
            manifest["file_count"], manifest["total_bytes"] / 1e6, prebuilt.BUNDLE_DIR
        )
    )
    return 0


def _check() -> int:
    manifest = prebuilt.load_manifest()
    if manifest is None:
        print("No prebuilt bundle manifest found.", file=sys.stderr)
        return 1
    problems = prebuilt.verify_bundle_bytes(manifest, prebuilt.BUNDLE_DIR)
    if problems:
        print("Bundle does not match its manifest: {}".format(problems[0]), file=sys.stderr)
        return 1
    if prebuilt.is_stale(manifest, FRONTEND_DIR):
        print(
            "Prebuilt bundle is stale: dashboard sources changed since it was built.\n"
            "Regenerate with: python3 scripts/build_prebuilt_dashboard.py --build",
            file=sys.stderr,
        )
        return 1
    print("Prebuilt dashboard bundle is current ({} files).".format(manifest["file_count"]))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--build", action="store_true", help="run npm ci + vite build, then commit")
    group.add_argument("--from-dist", metavar="DIR", help="regenerate from an existing build")
    group.add_argument("--check", action="store_true", help="verify without changing anything")
    args = parser.parse_args(argv)

    if args.check:
        return _check()
    if args.build:
        _npm_build()
        return _regenerate(FRONTEND_DIR / "dist")
    return _regenerate(Path(args.from_dist).resolve())


if __name__ == "__main__":
    raise SystemExit(main())
