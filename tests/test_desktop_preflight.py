"""Gates on the desktop preflight report.

The point of the module under test is that it names the *specific* blocked
prerequisite, so these tests assert which check fails rather than only that one
did. No test may open a real socket.
"""

from __future__ import annotations

import ast
import socket
import sys
from pathlib import Path

import pytest

from desktop import preflight

REPO_ROOT = Path(__file__).resolve().parents[1]


def _by_id(report: dict, check_id: str) -> dict:
    for check in report["checks"]:
        if check["id"] == check_id:
            return check
    raise AssertionError(f"no check with id {check_id!r} in {[c['id'] for c in report['checks']]}")


@pytest.fixture(autouse=True)
def _forbid_real_network(monkeypatch):
    def blocked(*args, **kwargs):  # pragma: no cover - only runs on regression
        raise AssertionError("preflight tests must never open a real socket")

    monkeypatch.setattr(preflight.socket, "create_connection", blocked)


def _offline(monkeypatch) -> None:
    def unreachable(*args, **kwargs):
        raise socket.gaierror("Name or service not known")

    monkeypatch.setattr(preflight.socket, "create_connection", unreachable)


def test_repo_checkout_passes_its_own_preflight(monkeypatch) -> None:
    monkeypatch.setattr(preflight, "_probe", lambda host: {"ok": True, "why": ""})
    report = preflight.run_checks(REPO_ROOT)
    assert _by_id(report, "checkout_intact")["ok"]
    assert _by_id(report, "checkout_writable")["ok"]
    assert _by_id(report, "python_version")["ok"]
    assert _by_id(report, "venv_available")["ok"]


def test_node_is_not_required_when_the_prebuilt_bundle_is_present(monkeypatch) -> None:
    """The regression test for the dialog that wrongly blamed Node.js."""
    monkeypatch.setattr(preflight.shutil, "which", lambda command: None)

    check = preflight.check_dashboard_bundle(REPO_ROOT)

    assert check["ok"]
    assert "prebuilt" in check["detail"].lower()


def test_translocated_checkout_is_named_as_the_cause() -> None:
    check = preflight.check_checkout_intact(
        Path("/private/var/folders/x/AppTranslocation/ABC/d/moneysweep-pr")
    )
    assert not check["ok"]
    assert "read-only copy" in check["detail"]
    assert "PRII-MONEYSWEEP.command" in check["remedy"]


def test_incomplete_checkout_is_named_as_the_cause(tmp_path: Path) -> None:
    check = preflight.check_checkout_intact(tmp_path)
    assert not check["ok"]
    assert "desktop/setup.py" in check["detail"]


def test_old_python_reports_a_usable_alternative_when_one_exists(monkeypatch) -> None:
    monkeypatch.setattr(preflight.sys, "version_info", (3, 9, 6))
    monkeypatch.setattr(preflight, "_find_supported_python", lambda: "/opt/homebrew/bin/python3")

    check = preflight.check_python_version()

    assert not check["ok"]
    assert "3.9.6" in check["detail"]
    assert "/opt/homebrew/bin/python3" in check["remedy"]


def test_old_python_falls_back_to_the_download_link(monkeypatch) -> None:
    monkeypatch.setattr(preflight.sys, "version_info", (3, 9, 6))
    monkeypatch.setattr(preflight, "_find_supported_python", lambda: None)

    assert "python.org" in preflight.check_python_version()["remedy"]


def test_offline_failure_names_the_network_and_not_node(monkeypatch, tmp_path) -> None:
    _offline(monkeypatch)
    monkeypatch.setattr(preflight, "_has_wheelhouse", lambda root: False)

    checks = preflight.check_network(REPO_ROOT, needed=True)

    assert not _by_id({"checks": checks}, "network_pypi")["ok"]
    joined = " ".join(check["detail"] for check in checks)
    assert "node" not in joined.lower()


def test_network_is_not_probed_when_no_downloads_are_needed(monkeypatch) -> None:
    # The autouse fixture makes any real socket call an error, so reaching the
    # network here would fail the test rather than pass silently.
    checks = preflight.check_network(REPO_ROOT, needed=False)
    assert len(checks) == 1 and checks[0]["ok"]


def test_wheelhouse_removes_the_network_requirement(monkeypatch, tmp_path) -> None:
    wheelhouse = tmp_path / "wheelhouse"
    wheelhouse.mkdir()
    (wheelhouse / "example-1.0-py3-none-any.whl").write_bytes(b"")
    monkeypatch.setenv("PRII_WHEELHOUSE", str(wheelhouse))

    checks = preflight.check_network(REPO_ROOT, needed=True)

    assert len(checks) == 1 and checks[0]["ok"]
    assert "wheelhouse" in checks[0]["detail"]


def test_low_disk_space_is_reported(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        preflight.shutil, "disk_usage", lambda path: type("U", (), {"free": 100 * 1024 * 1024})()
    )
    check = preflight.check_disk_space(tmp_path)
    assert not check["ok"]
    assert "1.5 GB" in check["remedy"] or "1.5 GB" in check["detail"]


def test_report_shape_is_stable(monkeypatch) -> None:
    monkeypatch.setattr(preflight, "_probe", lambda host: {"ok": True, "why": ""})
    report = preflight.run_checks(REPO_ROOT)
    assert report["schema_version"] == "moneysweep_desktop_preflight_v1"
    assert set(report) == {
        "schema_version",
        "repo_root",
        "setup_complete",
        "ok",
        "failed",
        "checks",
    }
    for check in report["checks"]:
        assert set(check) == {"id", "ok", "detail", "remedy"}
        assert isinstance(check["ok"], bool)


def test_text_report_lists_every_failure_with_a_remedy() -> None:
    report = {
        "ok": False,
        "checks": [
            {"id": "a", "ok": False, "detail": "first problem", "remedy": "do this"},
            {"id": "b", "ok": True, "detail": "fine", "remedy": ""},
        ],
    }
    text = preflight.format_text(report)
    assert "first problem" in text and "do this" in text
    assert "fine" not in text


def test_module_stays_importable_on_the_python_39_that_macos_ships() -> None:
    """macOS Command Line Tools ship 3.9, and reporting that is this module's job."""
    source = (REPO_ROOT / "desktop" / "preflight.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        assert not isinstance(node, ast.Match), "match statements need Python 3.10+"
        if isinstance(node, ast.AnnAssign) and node.simple:
            assert not isinstance(node.annotation, ast.BinOp), "X | Y annotations need 3.10+"
    compile(source, "preflight.py", "exec")
    assert sys.version_info >= (3, 9)
