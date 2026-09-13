from __future__ import annotations

import hashlib
import json
from pathlib import Path

from desktop import workspace


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_workspace_bootstrap_is_outside_resources_and_idempotent(monkeypatch, tmp_path):
    target = tmp_path / "user-workspace"
    monkeypatch.setenv("MONEYSWEEP_WORKSPACE_ROOT", str(target))

    first = workspace.bootstrap_workspace()
    assert first == target.resolve()
    assert first != workspace.resource_root()
    assert workspace.resource_root() not in first.parents

    receipt_path = first / "receipts" / "desktop_bootstrap_latest.json"
    assert receipt_path.exists()
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["policy"] == "COPY_MISSING_ONLY_NEVER_OVERWRITE_WORKSPACE_DATA"

    canon = first / "data" / "canonical_v1"
    seeded = sorted(p for p in canon.rglob("*") if p.is_file())
    assert seeded, "standalone workspace must seed at least one canonical file"

    sentinel = seeded[0]
    sentinel.write_bytes(b"USER_WORKSPACE_SENTINEL\n")
    before = _sha256(sentinel)

    second = workspace.bootstrap_workspace()
    assert second == first
    assert _sha256(sentinel) == before, "second boot must never overwrite workspace data"


def test_workspace_bootstrap_creates_required_mutable_roots(monkeypatch, tmp_path):
    target = tmp_path / "workspace"
    monkeypatch.setenv("MONEYSWEEP_WORKSPACE_ROOT", str(target))
    root = workspace.bootstrap_workspace()

    for rel in (
        "data/canonical_v1",
        "data/manual",
        "data/raw",
        "data/staging",
        "data/staging/processed",
        "data/logs",
        "data/receipts",
        "receipts",
    ):
        # data/receipts is created by the workspace bootstrap contract; the
        # top-level receipts tree holds application/runtime provenance receipts.
        assert (root / rel).exists(), rel
