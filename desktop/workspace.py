"""Writable desktop workspace bootstrap for standalone MoneySweep builds.

The application bundle is treated as immutable. Seed/canonical data is copied
once into a per-user workspace and all subsequent mutable data (manual drops,
API materialization outputs, receipts, logs) lives outside the .app bundle.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

APP_DIR_NAME = "PRII-MONEYSWEEP"
WORKSPACE_SCHEMA_VERSION = "1.0.0"


def resource_root() -> Path:
    """Return the immutable resource root for source or PyInstaller builds."""
    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root:
        return Path(frozen_root).resolve()
    return Path(__file__).resolve().parents[1]


def workspace_root() -> Path:
    """Return the writable per-user MoneySweep workspace."""
    override = os.environ.get("MONEYSWEEP_WORKSPACE_ROOT")
    if override:
        return Path(override).expanduser().resolve()

    home = Path.home()
    if sys.platform == "darwin":
        return home / "Library" / "Application Support" / APP_DIR_NAME
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", str(home / "AppData" / "Local")))
        return base / APP_DIR_NAME
    base = Path(os.environ.get("XDG_DATA_HOME", str(home / ".local" / "share")))
    return base / APP_DIR_NAME


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _copy_seed_tree(src: Path, dst: Path) -> list[dict[str, object]]:
    """Copy only missing seed files; never overwrite user/workspace state."""
    copied: list[dict[str, object]] = []
    if not src.exists():
        return copied
    for source in sorted(p for p in src.rglob("*") if p.is_file()):
        relative = source.relative_to(src)
        target = dst / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            continue
        shutil.copy2(source, target)
        copied.append(
            {
                "path": relative.as_posix(),
                "bytes": target.stat().st_size,
                "sha256": _sha256(target),
            }
        )
    return copied


def bootstrap_workspace() -> Path:
    """Create an idempotent writable workspace and seed the bundled canon."""
    root = workspace_root()
    data_root = root / "data"
    for rel in (
        "canonical_v1",
        "manual",
        "raw",
        "staging",
        "staging/processed",
        "logs",
        "receipts",
    ):
        (data_root / rel).mkdir(parents=True, exist_ok=True)

    resources = resource_root()
    copied = _copy_seed_tree(resources / "data" / "canonical_v1", data_root / "canonical_v1")

    os.environ["MONEYSWEEP_WORKSPACE_ROOT"] = str(root)
    os.environ["MONEYSWEEP_DATA_ROOT"] = str(data_root)
    # Registry/schema/code stay immutable inside the application resources.
    os.environ["MONEYSWEEP_RESOURCE_ROOT"] = str(resources)
    os.environ["MONEYSWEEP_REGISTRY_ROOT"] = str(resources)

    receipt = {
        "schema_version": WORKSPACE_SCHEMA_VERSION,
        "workspace": str(root),
        "resource_root": str(resources),
        "bootstrap_utc": datetime.now(timezone.utc).isoformat(),
        "seed_files_copied": copied,
        "seed_copy_count": len(copied),
        "policy": "COPY_MISSING_ONLY_NEVER_OVERWRITE_WORKSPACE_DATA",
    }
    receipt_path = root / "receipts" / "desktop_bootstrap_latest.json"
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return root
