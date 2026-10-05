"""Enforce the boundary around shared federation-rendered files.

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

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DRIFT_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "template-drift.yml"

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


def test_template_drift_workflow_is_the_byte_authority() -> None:
    text = DRIFT_WORKFLOW.read_text(encoding="utf-8")
    assert "PRII_TEMPLATE_REF:" in text
    assert "tools/render_federation_templates.py" in text
    assert "--repo moneysweep-pr" in text
    assert "--check" in text


def test_declared_template_rendered_paths_exist() -> None:
    missing = [
        relative for relative in TEMPLATE_RENDERED_PATHS if not (REPO_ROOT / relative).exists()
    ]
    assert missing == []


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
