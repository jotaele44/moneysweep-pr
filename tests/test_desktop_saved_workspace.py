"""The workspace chosen in Setup & Diagnostics must drive the backend data root."""

from __future__ import annotations

import pytest

pytest.importorskip("prii_desktop")

from prii_desktop import DesktopConfig  # noqa: E402
from prii_desktop.setup_center import configure  # noqa: E402

from desktop import config as desktop_config_module  # noqa: E402
from desktop import launch, workspace  # noqa: E402


_ENV = ("MONEYSWEEP_WORKSPACE_ROOT", "MONEYSWEEP_DATA_ROOT", "PRII_DATA_HOME")


def _clear_env(monkeypatch):
    """Unset the workspace variables and restore them at teardown."""
    for name in _ENV:
        monkeypatch.setenv(name, "")  # registers restoration of any prior value
        monkeypatch.delenv(name)


@pytest.fixture
def desktop_config(tmp_path, monkeypatch):
    _clear_env(monkeypatch)
    config = DesktopConfig.from_module(desktop_config_module)
    config.state_dir = tmp_path / "state"
    return config


def test_config_routes_selection_to_moneysweep_workspace_variable():
    config = DesktopConfig.from_module(desktop_config_module)
    assert config.data_env_var == "MONEYSWEEP_WORKSPACE_ROOT"
    assert config.setup_action == "desktop.workspace:bootstrap_workspace"


def test_save_bootstraps_data_tree_in_chosen_workspace(desktop_config, tmp_path, monkeypatch):
    chosen = tmp_path / "Financials"
    configure(desktop_config, chosen)

    assert workspace.workspace_root() == chosen.resolve()
    data_root = chosen.resolve() / "data"
    assert (data_root / "canonical_v1").is_dir()
    assert (data_root / "receipts").is_dir()
    assert (chosen / "receipts" / "desktop_bootstrap_latest.json").is_file()
    import os

    assert os.environ["MONEYSWEEP_DATA_ROOT"] == str(data_root)


def test_later_launch_applies_saved_workspace_before_bootstrap(
    desktop_config, tmp_path, monkeypatch
):
    chosen = tmp_path / "Financials"
    configure(desktop_config, chosen)
    # Simulate a fresh process: nothing exported yet.
    _clear_env(monkeypatch)

    launch._apply_saved_workspace(desktop_config)
    assert workspace.bootstrap_workspace() == chosen.resolve()


def test_explicit_environment_override_wins_over_saved_workspace(
    desktop_config, tmp_path, monkeypatch
):
    configure(desktop_config, tmp_path / "Financials")
    override = tmp_path / "override"
    monkeypatch.setenv("MONEYSWEEP_WORKSPACE_ROOT", str(override))

    launch._apply_saved_workspace(desktop_config)
    assert workspace.workspace_root() == override.resolve()


def test_no_saved_state_keeps_default_workspace(desktop_config, monkeypatch):
    launch._apply_saved_workspace(desktop_config)
    import os

    assert "MONEYSWEEP_WORKSPACE_ROOT" not in os.environ


def test_launch_script_does_not_shadow_stdlib_secrets(tmp_path):
    """``python desktop/launch.py`` (how every launcher starts the app) must import
    the backend without ``desktop/secrets.py`` shadowing the stdlib ``secrets``.

    Regression: starlette failed with "cannot import name 'token_hex'" inside the
    backend import, which left Setup & Diagnostics stuck on "Saving configuration".
    """
    import os
    import subprocess
    import sys
    from pathlib import Path

    for module in ("duckdb", "pyarrow", "keyring", "fastapi"):
        pytest.importorskip(module)

    script = Path(launch.__file__).resolve()
    result = subprocess.run(
        [sys.executable, str(script), "--selftest"],
        cwd=tmp_path,
        env={**os.environ, "MONEYSWEEP_WORKSPACE_ROOT": str(tmp_path / "ws")},
        capture_output=True,
        text=True,
        timeout=240,
    )
    output = result.stdout + result.stderr
    assert "token_hex" not in output, output[-2000:]
    assert '"selftest"' in result.stdout, output[-2000:]
