"""Keep the desktop fix inside this repository's own surface.

The macOS launchers are rendered federation templates shared with five sibling
repositories (``thehub-pr/federation-templates/targets.yaml``), and
``.github/workflows/template-drift.yml`` re-renders them at a pinned ref and fails
on any difference. Editing one here would both break that gate and make a
six-repository change without the federation control plane scoping it first.

Improvements to the launchers themselves are therefore a separate, coordinated
change landed in ``thehub-pr``. This test states that boundary so it is enforced
rather than merely remembered.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

# Rendered from thehub-pr/federation-templates at the ref pinned by
# .github/workflows/template-drift.yml. Byte-identical after placeholder
# substitution; must not be edited in this repository.
TEMPLATE_RENDERED_PATHS = (
    "Fix-Gatekeeper.command",
    "PRII-MONEYSWEEP.command",
    "PRII-MONEYSWEEP.sh",
    "PRII-MONEYSWEEP.bat",
    "PRII-MONEYSWEEP.app/Contents/MacOS/PRII-MONEYSWEEP",
    "requirements-desktop.txt",
    "dashboard/eslint.config.js",
)


def _merge_base() -> str | None:
    for ref in ("origin/main", "main"):
        probe = subprocess.run(
            ["git", "merge-base", "HEAD", ref], cwd=REPO_ROOT, capture_output=True, text=True
        )
        if probe.returncode == 0:
            return probe.stdout.strip()
    return None


@pytest.mark.parametrize("relative", TEMPLATE_RENDERED_PATHS)
def test_template_rendered_file_is_unchanged(relative: str) -> None:
    base = _merge_base()
    if base is None:
        pytest.skip("no main branch available to diff against")
    diff = subprocess.run(
        ["git", "diff", "--name-only", base, "--", relative],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert diff.returncode == 0
    assert diff.stdout.strip() == "", (
        f"{relative} is rendered from a shared federation template. Change it in "
        "thehub-pr/federation-templates/ and re-render, so every affected repository "
        "advances together; editing it here fails template-drift.yml."
    )


def test_the_setup_module_is_not_template_rendered() -> None:
    """desktop/*.py is repo-owned, which is why the fix lives there."""
    assert (REPO_ROOT / "desktop" / "setup.py").is_file()
    for relative in TEMPLATE_RENDERED_PATHS:
        assert not relative.startswith("desktop/")


def test_launchers_never_weaken_system_gatekeeper_policy() -> None:
    """A security ratchet: the fix must not disable assessment system-wide.

    Clearing com.apple.quarantine on files the user already owns is fine -- it is
    per-file and unprivileged. Turning off Gatekeeper assessment or SIP for the
    whole machine is not, and no launcher may start doing so.

    Plain ``sudo`` is not on this list: PRII-MONEYSWEEP.sh legitimately prints
    ``sudo apt install python3-venv`` as advice for the user to run themselves.
    """
    forbidden = ("spctl", "--master-disable", "csrutil")
    for relative in TEMPLATE_RENDERED_PATHS + ("desktop/setup.py",):
        path = REPO_ROOT / relative
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for token in forbidden:
            assert token not in text, f"{relative} must not contain {token!r}"
