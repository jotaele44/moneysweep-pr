"""Launch MoneySweep as a local desktop window.

The shared ``prii_desktop`` package owns the uvicorn/native-window lifecycle.
MoneySweep adds a mandatory pre-launch workspace bootstrap plus a frozen-binary
``--selftest`` used by release certification.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from prii_desktop import DesktopConfig, launch  # noqa: E402

from desktop import config  # noqa: E402
from desktop.workspace import bootstrap_workspace, resource_root, workspace_root  # noqa: E402


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
    bootstrap_workspace()
    if "--selftest" in sys.argv:
        raise SystemExit(_selftest())
    launch(DesktopConfig.from_module(config))


if __name__ == "__main__":
    main()
