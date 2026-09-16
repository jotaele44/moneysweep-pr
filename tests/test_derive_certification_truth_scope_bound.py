from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

import tools.derive_certification_truth_scope_bound as mod
from tools.certification_truth_guards import EvidenceError

pytestmark = pytest.mark.unit


def _fake_derive(*, root: Path, scope_dir: Path, **kwargs):
    del kwargs
    scope_dir.mkdir(parents=True)
    manifest = {
        "schema_version": "moneysweep.certification_scope/v2",
        "scope_identity": {
            "scope_repository_sha": "a" * 40,
            "truth_sha256": "b" * 64,
        },
        "scope_id": "c" * 64,
        "artifacts": {},
    }
    path = scope_dir / "scope_manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return {
        "truth": {},
        "scope_manifest": manifest,
        "scope_manifest_path": str(path),
    }


def _assert_tool_binding(manifest: dict) -> None:
    binding = manifest["scope_binding"]
    identity = manifest["scope_identity"]
    digest = binding["scope_binding_tool_sha256"]
    assert len(digest) == 64
    assert all(char in "0123456789abcdef" for char in digest)
    assert identity["scope_binding_tool_sha256"] == digest
    assert identity["scope_binding_schema_version"] == binding["schema_version"]


def test_distinct_evidence_repo_sha_is_bound(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "scope"
    evidence = tmp_path / "evidence"
    root.mkdir()
    evidence.mkdir()
    monkeypatch.setattr(mod, "derive", _fake_derive)
    monkeypatch.setattr(
        mod,
        "_git_head",
        lambda path: "a" * 40 if path.resolve() == root.resolve() else "d" * 40,
    )

    result = mod.derive_scope_bound(
        root=root,
        evidence_root=evidence,
        receipts_dir=None,
        execution_receipts_dir=None,
        scope_dir=tmp_path / "frozen",
        as_of=datetime(2026, 9, 16, tzinfo=timezone.utc),
    )

    binding = result["scope_manifest"]["scope_binding"]
    assert binding["scope_repository_sha"] == "a" * 40
    assert binding["evidence_repository_sha"] == "d" * 40
    assert binding["evidence_repository_same_as_scope"] is False
    assert binding["path_strings_are_identity"] is False
    assert result["scope_manifest"]["scope_identity"]["evidence_repository_sha"] == "d" * 40
    assert result["scope_manifest"]["scope_id"] != "c" * 64
    _assert_tool_binding(result["scope_manifest"])


def test_same_repo_binds_same_sha(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "scope"
    root.mkdir()
    monkeypatch.setattr(mod, "derive", _fake_derive)
    monkeypatch.setattr(mod, "_git_head", lambda path: "a" * 40)

    result = mod.derive_scope_bound(
        root=root,
        evidence_root=root,
        receipts_dir=None,
        execution_receipts_dir=None,
        scope_dir=tmp_path / "frozen",
        as_of=datetime(2026, 9, 16, tzinfo=timezone.utc),
    )

    binding = result["scope_manifest"]["scope_binding"]
    assert binding["evidence_repository_same_as_scope"] is True
    assert binding["evidence_repository_sha"] == binding["scope_repository_sha"] == "a" * 40
    _assert_tool_binding(result["scope_manifest"])


def test_missing_distinct_evidence_head_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "scope"
    evidence = tmp_path / "evidence"
    root.mkdir()
    evidence.mkdir()
    monkeypatch.setattr(mod, "derive", _fake_derive)
    monkeypatch.setattr(
        mod,
        "_git_head",
        lambda path: "a" * 40 if path.resolve() == root.resolve() else None,
    )

    with pytest.raises(EvidenceError, match="evidence_repository_head_unavailable"):
        mod.derive_scope_bound(
            root=root,
            evidence_root=evidence,
            receipts_dir=None,
            execution_receipts_dir=None,
            scope_dir=tmp_path / "frozen",
            as_of=datetime(2026, 9, 16, tzinfo=timezone.utc),
        )


def test_scope_head_mismatch_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "scope"
    root.mkdir()
    monkeypatch.setattr(mod, "derive", _fake_derive)
    monkeypatch.setattr(mod, "_git_head", lambda path: "e" * 40)

    with pytest.raises(EvidenceError, match="scope_repository_sha_mismatch"):
        mod.derive_scope_bound(
            root=root,
            evidence_root=root,
            receipts_dir=None,
            execution_receipts_dir=None,
            scope_dir=tmp_path / "frozen",
            as_of=datetime(2026, 9, 16, tzinfo=timezone.utc),
        )
