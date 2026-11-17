"""MoneySweep's Launch Pad declaration (desktop/config.py).

The screen itself lives in the shared prii_desktop runtime; these tests keep the
declaration true to this repository. They skip when the installed runtime
predates the Launch Pad.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

launchpad = pytest.importorskip("prii_desktop.launchpad")

from prii_desktop import DesktopConfig  # noqa: E402

from desktop import config  # noqa: E402

ROOT = Path(config.REPO_ROOT)
BACKEND = ROOT / "server" / "backend"
# The desktop app mounts these; case_manager_* is a separate app.
MOUNTED = ("main.py", "api_keys.py", "campaign_finance.py", "government_changes.py",
           "leaderboards.py", "ownership_api.py", "materialization.py")


def _spec():
    return launchpad.launchpad_spec(DesktopConfig.from_module(config))


def test_declaration_is_valid_two_mode_without_a_credential():
    spec = _spec()
    assert spec is not None and spec.has_modes
    assert spec.operator.token_env is None


def test_start_pages_are_real_tabs():
    dashboard = (ROOT / "dashboard/src/pages/Dashboard.jsx").read_text()
    for page in _spec().start_pages:
        assert page.route.startswith("/?tab="), page.route
        assert f"'{page.route.removeprefix('/?tab=')}'" in dashboard, page.route


def test_a_guest_is_allowed_no_write_because_none_is_a_pure_read():
    assert _spec().guest_allow == ()
    sources = "\n".join((BACKEND / name).read_text() for name in MOUNTED)
    writes = re.findall(r"@(?:app|router)\.(post|put|patch|delete)\(", sources)
    # A new non-GET route must be classified: a read-only one needs an allow
    # entry in LAUNCHPAD["guest_guard"], otherwise update this count.
    assert sorted(writes) == ["delete", "post", "post", "post", "post", "post", "put"], writes


def test_options_bind_variables_the_code_reads():
    code = (ROOT / "scripts/audit_hud_drgr_authorized_sources.py").read_text()
    for option in _spec().options:
        assert f'"{option.env}"' in code, option.env


def test_status_reads_the_bootstrapped_workspace(tmp_path, monkeypatch):
    data_root = tmp_path / "data"
    (data_root / "canonical_v1").mkdir(parents=True)
    (data_root / "canonical_v1" / "contracts.csv").write_text("id\n1\n2\n")
    (data_root / "canonical_v1" / "entities.csv").write_text("id\n1\n")
    (tmp_path / "receipts" / "materialization_runs").mkdir(parents=True)
    (tmp_path / "receipts" / "materialization_runs" / "run-1.json").write_text("{}")
    monkeypatch.setenv("MONEYSWEEP_DATA_ROOT", str(data_root))
    monkeypatch.setenv(config.DATA_ENV_VAR, str(tmp_path))

    rows = {row["label"]: row for row in config._launchpad_status()}

    assert rows["Canonical tables"]["value"] == "2 contracts, 1 entities"
    assert rows["Materialization runs"]["value"] == "1"
    assert rows["Release status"]["status"] in {"info", "pass"}


def test_status_falls_back_to_the_bundled_seed(monkeypatch):
    monkeypatch.delenv("MONEYSWEEP_DATA_ROOT", raising=False)
    monkeypatch.delenv(config.DATA_ENV_VAR, raising=False)
    rows = {row["label"]: row for row in config._launchpad_status()}
    assert rows["Canonical tables"]["status"] == "pass"
    assert rows["Materialization runs"]["value"] == "None yet"
