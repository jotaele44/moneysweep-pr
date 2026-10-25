"""Launch MoneySweep as a local desktop window.

The shared ``prii_desktop`` package owns the uvicorn/native-window lifecycle.
MoneySweep adds a mandatory pre-launch workspace bootstrap plus a frozen-binary
``--selftest`` used by release certification.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if not getattr(sys, "frozen", False):
    # Running ``python desktop/launch.py`` puts this directory first on sys.path,
    # where ``desktop/secrets.py`` shadows the standard-library ``secrets`` module
    # and breaks the backend import (starlette: "cannot import name 'token_hex'").
    # Drop it; the ``desktop`` package is imported from the repository root instead.
    # Skipped in a frozen app, where this directory is PyInstaller's extraction
    # root and must stay importable.
    sys.path[:] = [entry for entry in sys.path if Path(entry or ".").resolve() != _HERE]
sys.path.insert(0, str(_HERE.parent))

from prii_desktop import DesktopConfig, launch  # noqa: E402
from prii_desktop.setup_center import apply_environment, read_state  # noqa: E402

from desktop import config  # noqa: E402
from desktop.workspace import bootstrap_workspace, resource_root, workspace_root  # noqa: E402


def _apply_saved_workspace(desktop_config: DesktopConfig) -> None:
    """Point the process at the workspace chosen in Setup & Diagnostics.

    Must run before ``bootstrap_workspace`` so the data root follows the saved
    choice. An explicit ``MONEYSWEEP_WORKSPACE_ROOT`` in the environment wins.
    """
    if os.environ.get(desktop_config.data_env_var):
        return
    state = read_state(desktop_config)
    if state is not None:
        apply_environment(desktop_config, state)


def _selftest() -> int:
    """Exercise the exact frozen runtime without network or external tooling."""
    bootstrap_workspace()

    # These imports are deliberate certification gates: Contract Forensics and
    # Parquet materialization must be present inside the frozen application.
    import duckdb  # noqa: F401
    import pyarrow  # noqa: F401

    from server.backend.materialization import (
        ApiRunRequest,
        materialization_status,
        run_api_sources,
    )

    status = materialization_status()
    dry_run = run_api_sources(ApiRunRequest(dry_run=True))
    readiness = status.get("readiness") or {}

    checks = {
        "workspace_outside_bundle": resource_root() not in workspace_root().parents
        and workspace_root() != resource_root(),
        "registry_count_closes": status.get("registeredSources") == readiness.get("total_sources"),
        "automatable_count_closes": dry_run.get("selected_count")
        == readiness.get("automatable_total"),
        "dry_run_executed_no_sources": dry_run.get("dry_run") is True and not dry_run.get("ran"),
        "secrets_not_returned": status.get("secretsReturned") is False,
    }
    result = {
        "selftest": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "registered_sources": status.get("registeredSources"),
        "automatable_sources": dry_run.get("selected_count"),
        "production_status": (status.get("production") or {}).get("production_status"),
    }
    print(json.dumps(result, sort_keys=True))
    return 0 if all(checks.values()) else 1


def main() -> None:
    desktop_config = DesktopConfig.from_module(config)
    _apply_saved_workspace(desktop_config)
    bootstrap_workspace()
    if "--selftest" in sys.argv:
        raise SystemExit(_selftest())
    launch(desktop_config)


if __name__ == "__main__":
    main()
