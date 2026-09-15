"""Report exactly why the desktop wrapper's first run cannot proceed.

The wrapper used to collapse every possible failure into one dialog -- "It needs
internet the first time (and Node.js for the dashboard build)" -- which named the
wrong cause more often than the right one and left only a ``/var/folders`` log
path to go on. This module checks each prerequisite independently and reports the
specific one that failed, together with the action that fixes it.

Two rules shape the implementation:

* **Stdlib only, and importable on Python 3.9.** The macOS Command Line Tools
  ship 3.9, and telling the user their interpreter is too old is one of this
  module's jobs -- it cannot need 3.11 to say so.
* **No network probe unless pip work actually remains.** A checkout that is
  already set up must never touch the network just to render a status line.

Run directly for a report::

    python3 desktop/preflight.py            # human-readable
    python3 desktop/preflight.py --json     # machine-readable
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]

# Runnable as `python3 desktop/preflight.py`, which puts desktop/ on sys.path
# rather than the repo root, so the `desktop.*` imports below need this.
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

MIN_PYTHON = (3, 11)
MIN_FREE_BYTES = 1536 * 1024 * 1024  # pip's build dirs make sub-1.5GB installs fail oddly
NETWORK_TIMEOUT_SECONDS = 5
PYPI_HOSTS = ("pypi.org", "files.pythonhosted.org")
GIT_HOST = "github.com"

# Interpreters worth naming when the bootstrap one is too old. Finder launches the
# app with a minimal PATH, so an absolute path is often the only usable answer.
CANDIDATE_PYTHONS = (
    "/opt/homebrew/bin/python3",
    "/usr/local/bin/python3",
    "python3.13",
    "python3.12",
    "python3.11",
)

_VCS_REQUIREMENT = re.compile(r"^[^#]*\bgit\+", re.MULTILINE)


def _check(check_id: str, ok: bool, detail: str, remedy: str = "") -> Dict[str, Any]:
    return {"id": check_id, "ok": bool(ok), "detail": detail, "remedy": remedy if not ok else ""}


def check_checkout_intact(repo_root: Path) -> Dict[str, Any]:
    if "/AppTranslocation/" in str(repo_root):
        return _check(
            "checkout_intact",
            False,
            "macOS is running the app from a temporary read-only copy.",
            "Double-click PRII-MONEYSWEEP.command in the same folder; it fixes this "
            "permanently and starts the app.",
        )
    missing = [
        name
        for name in ("desktop/setup.py", "desktop/config.py", "dashboard")
        if not (repo_root / name).exists()
    ]
    if missing:
        return _check(
            "checkout_intact",
            False,
            "Not a complete checkout; missing {}.".format(", ".join(missing)),
            "Keep PRII-MONEYSWEEP.app inside the folder it came in, and open it from there.",
        )
    return _check("checkout_intact", True, "Checkout looks complete at {}.".format(repo_root))


def check_checkout_writable(repo_root: Path) -> Dict[str, Any]:
    try:
        with tempfile.NamedTemporaryFile(dir=str(repo_root), prefix=".prii-write-test"):
            pass
    except OSError as exc:
        return _check(
            "checkout_writable",
            False,
            "Cannot write into {} ({}).".format(repo_root, exc.strerror or exc),
            "Move the folder somewhere you own, such as your home folder, and try again.",
        )
    return _check("checkout_writable", True, "Checkout is writable.")


def _find_supported_python() -> Optional[str]:
    for candidate in CANDIDATE_PYTHONS:
        resolved = candidate if os.path.isabs(candidate) else shutil.which(candidate)
        if not resolved or not os.path.exists(resolved):
            continue
        try:
            out = subprocess.run(
                [resolved, "-c", "import sys; print('%d.%d' % sys.version_info[:2])"],
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if out.returncode:
            continue
        parts = out.stdout.strip().split(".")
        if len(parts) == 2 and all(p.isdigit() for p in parts):
            if (int(parts[0]), int(parts[1])) >= MIN_PYTHON:
                return resolved
    return None


def check_python_version() -> Dict[str, Any]:
    running = "{}.{}.{}".format(*sys.version_info[:3])
    if sys.version_info >= MIN_PYTHON:
        return _check("python_version", True, "Python {} is supported.".format(running))
    alternative = _find_supported_python()
    remedy = (
        "Run the setup with {} instead.".format(alternative)
        if alternative
        else "Install Python {}.{}+ from https://www.python.org/downloads/".format(*MIN_PYTHON)
    )
    return _check(
        "python_version",
        False,
        "Python {}.{}+ is required; this is {}.".format(MIN_PYTHON[0], MIN_PYTHON[1], running),
        remedy,
    )


def check_venv_available() -> Dict[str, Any]:
    missing = [m for m in ("venv", "ensurepip") if importlib.util.find_spec(m) is None]
    if missing:
        return _check(
            "venv_available",
            False,
            "This Python cannot create virtual environments (missing {}).".format(
                ", ".join(missing)
            ),
            "On Debian/Ubuntu install python3-venv; on macOS use the python.org installer.",
        )
    return _check("venv_available", True, "Virtual environments are available.")


def _node_is_supported() -> bool:
    node = shutil.which("node")
    if node is None or shutil.which("npm") is None:
        return False
    try:
        raw = subprocess.run(
            [node, "--version"], capture_output=True, text=True, timeout=10
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return False
    try:
        from desktop.setup import node_version_supported
    except ImportError:  # pragma: no cover - only when imported outside the checkout
        return False
    return node_version_supported(raw)


def check_dashboard_bundle(repo_root: Path) -> Dict[str, Any]:
    """Node is only genuinely required when neither a built nor a prebuilt UI exists."""
    if (repo_root / "dashboard" / "dist" / "index.html").is_file():
        return _check("dashboard_bundle", True, "Dashboard is already built.")
    try:
        from desktop import prebuilt

        manifest = prebuilt.load_manifest()
        if manifest is not None and not prebuilt.verify_bundle_bytes(manifest, prebuilt.BUNDLE_DIR):
            return _check(
                "dashboard_bundle",
                True,
                "Using the committed prebuilt dashboard ({} files); Node.js is not needed.".format(
                    manifest.get("file_count", "?")
                ),
            )
    except (ImportError, OSError, ValueError):  # a broken bundle must not break reporting
        pass
    if _node_is_supported():
        return _check("dashboard_bundle", True, "Node.js is available to build the dashboard.")
    return _check(
        "dashboard_bundle",
        False,
        "No dashboard build is available and Node.js is missing or unsupported.",
        "Install Node.js 22.22.2+ from https://nodejs.org, or use a checkout that "
        "includes desktop/prebuilt-dashboard/.",
    )


def _requirement_files(repo_root: Path) -> List[Path]:
    return [
        repo_root / "requirements.txt",
        repo_root / "server" / "backend" / "requirements.txt",
        repo_root / "requirements-desktop.txt",
    ]


def _needs_vcs_requirements(repo_root: Path) -> bool:
    for path in _requirement_files(repo_root):
        try:
            if _VCS_REQUIREMENT.search(path.read_text(encoding="utf-8")):
                return True
        except OSError:
            continue
    return False


def _has_wheelhouse(repo_root: Path) -> bool:
    raw = os.environ.get("PRII_WHEELHOUSE")
    wheelhouse = Path(raw) if raw else repo_root / "desktop" / "wheelhouse"
    return wheelhouse.is_dir() and any(wheelhouse.glob("*.whl"))


def check_git_available(repo_root: Path) -> Dict[str, Any]:
    if not _needs_vcs_requirements(repo_root) or _has_wheelhouse(repo_root):
        return _check("git_available", True, "No git-sourced requirement needs installing.")
    if shutil.which("git") is None:
        return _check(
            "git_available",
            False,
            "Some requirements install from git+https:// URLs, but git is not installed.",
            "Install the Xcode Command Line Tools with: xcode-select --install",
        )
    return _check("git_available", True, "git is available for git+https requirements.")


def _probe(host: str) -> Dict[str, Any]:
    try:
        socket.create_connection((host, 443), timeout=NETWORK_TIMEOUT_SECONDS).close()
    except socket.gaierror:
        return {
            "ok": False,
            "why": "cannot resolve {} (offline, or DNS is not working)".format(host),
        }
    except socket.timeout:
        return {
            "ok": False,
            "why": "connection to {} timed out (captive portal or proxy?)".format(host),
        }
    except OSError as exc:
        return {"ok": False, "why": "cannot reach {} ({})".format(host, exc.strerror or exc)}
    return {"ok": True, "why": ""}


def check_network(repo_root: Path, needed: bool) -> List[Dict[str, Any]]:
    if not needed:
        return [_check("network", True, "Setup is already complete; no downloads needed.")]
    if _has_wheelhouse(repo_root):
        return [_check("network", True, "Using the offline wheelhouse; no downloads needed.")]
    results = []
    failures = [r["why"] for r in (_probe(h) for h in PYPI_HOSTS) if not r["ok"]]
    results.append(
        _check(
            "network_pypi",
            not failures,
            "PyPI is reachable." if not failures else failures[0],
            "Connect to the internet, or copy desktop/wheelhouse/ from a machine where "
            "setup already worked (see docs/DESKTOP_OFFLINE_BOOTSTRAP.md).",
        )
    )
    if _needs_vcs_requirements(repo_root):
        probe = _probe(GIT_HOST)
        results.append(
            _check(
                "network_github",
                probe["ok"],
                "github.com is reachable." if probe["ok"] else probe["why"],
                "Some requirements install directly from GitHub; that host must be reachable.",
            )
        )
    return results


def check_disk_space(repo_root: Path) -> Dict[str, Any]:
    try:
        free = shutil.disk_usage(str(repo_root)).free
    except OSError as exc:
        return _check("disk_space", True, "Could not measure free space ({}).".format(exc))
    if free < MIN_FREE_BYTES:
        return _check(
            "disk_space",
            False,
            "Only {:.1f} GB free; the install needs about 1.5 GB.".format(free / 1e9),
            "Free up disk space and try again.",
        )
    return _check("disk_space", True, "{:.1f} GB free.".format(free / 1e9))


def setup_is_complete(repo_root: Path) -> bool:
    marker = repo_root / "desktop" / ".setup-complete"
    venv_python = repo_root / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    dist_index = repo_root / "dashboard" / "dist" / "index.html"
    return marker.exists() and venv_python.exists() and dist_index.exists()


def run_checks(repo_root: Optional[Path] = None) -> Dict[str, Any]:
    root = repo_root or REPO_ROOT
    checks: List[Dict[str, Any]] = [check_checkout_intact(root)]
    if checks[0]["ok"]:
        checks.append(check_checkout_writable(root))
    checks.append(check_python_version())
    checks.append(check_venv_available())
    checks.append(check_dashboard_bundle(root))
    checks.append(check_git_available(root))
    checks.extend(check_network(root, needed=not setup_is_complete(root)))
    checks.append(check_disk_space(root))
    return {
        "schema_version": "moneysweep_desktop_preflight_v1",
        "repo_root": str(root),
        "setup_complete": setup_is_complete(root),
        "ok": all(check["ok"] for check in checks),
        "failed": [check["id"] for check in checks if not check["ok"]],
        "checks": checks,
    }


def format_text(report: Dict[str, Any]) -> str:
    if report["ok"]:
        return "All desktop prerequisites are satisfied."
    lines = ["What is blocking setup:"]
    for check in report["checks"]:
        if not check["ok"]:
            lines.append("  ✘ {}".format(check["detail"]))
            if check["remedy"]:
                lines.append("    → {}".format(check["remedy"]))
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", action="store_true", help="emit the machine-readable report")
    args = parser.parse_args(argv)
    report = run_checks()
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(format_text(report))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
