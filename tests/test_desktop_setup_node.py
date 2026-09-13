from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from desktop import setup

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_desktop_node_engine_matches_dashboard_metadata() -> None:
    package = json.loads((REPO_ROOT / "dashboard/package.json").read_text(encoding="utf-8"))
    assert setup.NODE_ENGINE == package["engines"]["node"]
    assert (REPO_ROOT / "dashboard/.npmrc").read_text(encoding="utf-8") == ("engine-strict=true\n")


def test_node_guard_is_classified_as_internal_capability() -> None:
    extension = json.loads(
        (
            REPO_ROOT / ".federation/gui-capabilities.extensions/dashboard-node-runtime.json"
        ).read_text(encoding="utf-8")
    )
    capability = extension["capabilities"][0]
    assert capability["classification"] == "internal"
    assert capability["candidate_ids"] == ["python_symbol:desktop/setup.py:node_version_supported"]


@pytest.mark.parametrize(
    "version",
    ("v22.22.2", "22.99.0", "v24.15.0", "24.99.1", "v26.0.0", "27.1.0"),
)
def test_node_version_supported_accepts_jsdom_30_runtimes(version: str) -> None:
    assert setup.node_version_supported(version)


@pytest.mark.parametrize(
    "version",
    ("v20.20.0", "v22.22.1", "v23.99.0", "v24.14.9", "v25.99.0", "unknown", ""),
)
def test_node_version_supported_rejects_unsupported_runtimes(version: str) -> None:
    assert not setup.node_version_supported(version)


def test_setup_frontend_rejects_node_20_before_npm_install(monkeypatch) -> None:
    monkeypatch.setattr(setup.shutil, "which", lambda command: f"/usr/bin/{command}")
    monkeypatch.setattr(
        setup.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(stdout="v20.20.0\n"),
    )

    with pytest.raises(SystemExit, match=r"Node\.js .* required .* found v20\.20\.0"):
        setup.setup_frontend()
