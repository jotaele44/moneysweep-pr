"""One-time setup for the desktop wrapper (stdlib only).

Creates a private .venv, installs the backend + desktop requirements, and makes
the frontend available for same-origin serving (empty VITE_API_BASE). Idempotent:
re-runs are skipped via a marker file unless --force is given.

The frontend is taken from the committed prebuilt bundle when one is available,
so a fresh checkout no longer needs Node.js on first run; pass --build-frontend
(or set PRII_FORCE_FRONTEND_BUILD=1) to build it from source instead. Requirements
install from desktop/wheelhouse/ when that directory holds wheels, which makes the
whole first run work offline -- see docs/DESKTOP_OFFLINE_BOOTSTRAP.md.

Usage:
  python desktop/setup.py            run setup (skips when already complete)
  python desktop/setup.py --ensure   quiet fast-path used by the launchers
  python desktop/setup.py --force    redo setup from scratch
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import venv
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from desktop import config, prebuilt, preflight  # noqa: E402
from desktop.config import DIST_DIR, FRONTEND_DIR, REPO_ROOT, REQUIREMENT_FILES  # noqa: E402

VENV_DIR = REPO_ROOT / ".venv"
MARKER = Path(__file__).resolve().parent / ".setup-complete"
MIN_PYTHON = (3, 11)
CONSTRAINTS_FILE = REPO_ROOT / "constraints-desktop.txt"
NODE_ENGINE = "^22.22.2 || ^24.15.0 || >=26.0.0"
WHEELHOUSE_DIR = REPO_ROOT / "desktop" / "wheelhouse"

# Cleared of macOS quarantine after a successful run so the second launch never
# hits Gatekeeper again. Enumerated rather than recursive: data/ is hundreds of
# megabytes, and walking it would stall the launcher with no visible progress.
QUARANTINE_TARGETS = (
    "PRII-MONEYSWEEP.app",
    "PRII-MONEYSWEEP.command",
    "PRII-MONEYSWEEP.sh",
    "Fix-Gatekeeper.command",
    "desktop",
)


def venv_python() -> Path:
    if os.name == "nt":
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def run(cmd: list[str], cwd: Path | None = None, env: dict[str, str] | None = None) -> None:
    print(f"$ {' '.join(cmd)}")
    subprocess.run(cmd, cwd=cwd, env=env, check=True)


def is_complete() -> bool:
    return MARKER.exists() and venv_python().exists() and (DIST_DIR / "index.html").exists()


def wheelhouse_dir() -> Path:
    raw = os.environ.get("PRII_WHEELHOUSE")
    return Path(raw).expanduser() if raw else WHEELHOUSE_DIR


def has_wheelhouse() -> bool:
    """True when a local wheel cache can satisfy the install without any network."""
    directory = wheelhouse_dir()
    return directory.is_dir() and any(directory.glob("*.whl"))


def clear_macos_quarantine() -> None:
    """Drop com.apple.quarantine from the launchers so later launches are clean.

    macOS marks everything extracted from a downloaded ZIP, which is what makes
    Gatekeeper block the app and then run it translocated. Clearing the flag once
    setup has succeeded is what removes the repeat prompt and the whole
    Fix-Gatekeeper detour. Purely a convenience: failures are ignored, and no
    system-wide assessment policy is touched.
    """
    if sys.platform != "darwin" or shutil.which("xattr") is None:
        return
    for name in QUARANTINE_TARGETS:
        target = REPO_ROOT / name
        if not target.exists():
            continue
        try:
            subprocess.run(
                ["xattr", "-dr", "com.apple.quarantine", str(target)],
                check=False,
                capture_output=True,
                timeout=60,
            )
        except (OSError, subprocess.SubprocessError):
            continue


def setup_python() -> None:
    if sys.version_info < MIN_PYTHON:
        raise SystemExit(f"Python 3.11+ required, found {sys.version.split()[0]}")
    if not venv_python().exists():
        print(f"Creating virtual environment at {VENV_DIR} …")
        venv.EnvBuilder(with_pip=True, clear=False).create(VENV_DIR)
    pip = [str(venv_python()), "-m", "pip", "install", "--upgrade", "pip", "--quiet"]
    if not has_wheelhouse():
        run(pip)
    install = [str(venv_python()), "-m", "pip", "install", "--quiet"]
    for req in REQUIREMENT_FILES:
        install += ["-r", str(req)]
    if CONSTRAINTS_FILE.exists():
        install += ["-c", str(CONSTRAINTS_FILE)]
    if has_wheelhouse():
        # An operator copied a wheel cache across from a machine where setup
        # already worked; install from it alone so the run needs no network.
        print(f"Installing from the offline wheelhouse at {wheelhouse_dir()} …")
        install += ["--no-index", "--find-links", str(wheelhouse_dir())]
    run(install)
    extra = list(getattr(config, "EXTRA_PIP_SPECS", []))
    if extra:
        run([str(venv_python()), "-m", "pip", "install", "--quiet", *extra])


def node_version_supported(raw_version: str) -> bool:
    token = raw_version.strip().removeprefix("v").split("-", 1)[0]
    parts = token.split(".")
    if len(parts) != 3 or not all(part.isdigit() for part in parts):
        return False
    version = tuple(int(part) for part in parts)
    major = version[0]
    return (
        (major == 22 and version >= (22, 22, 2))
        or (major == 24 and version >= (24, 15, 0))
        or major >= 26
    )


def source_build_available() -> bool:
    """True when npm and a dashboard-supported Node are both present."""
    npm = shutil.which("npm")
    node = shutil.which("node")
    if npm is None or node is None:
        return False
    try:
        installed = subprocess.run(
            [node, "--version"], check=True, capture_output=True, text=True, timeout=30
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return False
    return node_version_supported(installed)


def setup_frontend(*, force_build: bool = False) -> None:
    """Put a built dashboard at DIST_DIR, preferring the committed bundle.

    Order matters: an existing build wins (a developer's own `npm run dev` output
    is never clobbered), then the prebuilt bundle, and only then npm -- which is
    the step that used to make Node.js a hard prerequisite of every first run.
    """
    if not force_build:
        if (DIST_DIR / "index.html").exists():
            return
        if prebuilt.install_prebuilt_dashboard(
            DIST_DIR,
            frontend_dir=FRONTEND_DIR,
            source_build_available=source_build_available(),
        ):
            print(f"Installed the committed prebuilt dashboard into {DIST_DIR}.")
            return
    _build_frontend_from_source()
    prebuilt.record_source_build()


def _build_frontend_from_source() -> None:
    npm = shutil.which("npm")
    node = shutil.which("node")
    if npm is None or node is None:
        raise SystemExit(
            "npm not found. Install Node.js (https://nodejs.org) and re-run python desktop/setup.py"
        )
    installed_node = subprocess.run(
        [node, "--version"], check=True, capture_output=True, text=True
    ).stdout.strip()
    if not node_version_supported(installed_node):
        raise SystemExit(
            f"Node.js {NODE_ENGINE} required by the dashboard, found {installed_node or 'unknown'}"
        )
    env = dict(os.environ)
    env["VITE_API_BASE"] = ""
    env.update(getattr(config, "EXTRA_BUILD_ENV", {}))
    if (FRONTEND_DIR / "package-lock.json").exists():
        run([npm, "ci", "--no-audit", "--no-fund"], cwd=FRONTEND_DIR, env=env)
    else:
        run([npm, "install", "--no-audit", "--no-fund"], cwd=FRONTEND_DIR, env=env)
    run([npm, "run", "build"], cwd=FRONTEND_DIR, env=env)
    if not (DIST_DIR / "index.html").exists():
        raise SystemExit(f"Frontend build did not produce {DIST_DIR / 'index.html'}")


def report_blocking_prerequisites() -> str:
    """Human-readable reason setup cannot proceed, or '' when nothing blocks it."""
    try:
        report = preflight.run_checks(REPO_ROOT)
    except Exception:  # pragma: no cover - diagnostics must never mask the real error
        return ""
    return "" if report["ok"] else preflight.format_text(report)


def main() -> None:
    args = set(sys.argv[1:])
    if "--force" in args:
        MARKER.unlink(missing_ok=True)
    if is_complete():
        if "--ensure" not in args:
            print("Setup already complete (use --force to redo).")
        clear_macos_quarantine()
        return
    # Only the bootstrap interpreter has to satisfy this; a finished install runs
    # from .venv and is let through above, so losing python3.11+ from PATH later
    # does not strand a working app. Checked before setup_python() because macOS
    # ships 3.9 with the Command Line Tools, and cloning the hub sibling first
    # would bury the one line that says what is actually wrong.
    if sys.version_info < MIN_PYTHON:
        raise SystemExit(f"Python 3.11+ required, found {sys.version.split()[0]}")
    # Fail in seconds with the actual cause rather than after a multi-minute pip
    # run that ends in a dialog blaming the network for a missing Node.js.
    blocking = report_blocking_prerequisites()
    if blocking:
        raise SystemExit(blocking)
    setup_python()
    force_build = (
        "--force" in args
        or "--build-frontend" in args
        or os.environ.get("PRII_FORCE_FRONTEND_BUILD") == "1"
    )
    setup_frontend(force_build=force_build)
    MARKER.write_text("ok\n", encoding="utf-8")
    clear_macos_quarantine()
    print("Desktop setup complete.")


if __name__ == "__main__":
    main()
