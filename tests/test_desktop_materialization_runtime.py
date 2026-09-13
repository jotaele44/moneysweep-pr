from __future__ import annotations

import json
from pathlib import Path

import scripts.config as script_config
import scripts.run_automatable_sources as materialization_runner
from scripts.run_automatable_sources import _bind_legacy_config_to_workspace, run


def _snapshot_path_globals(module):
    snapshot = {}
    for name, value in vars(module).items():
        if isinstance(value, Path):
            snapshot[name] = value
        elif isinstance(value, list) and value and all(isinstance(item, Path) for item in value):
            snapshot[name] = list(value)
        elif isinstance(value, tuple) and value and all(isinstance(item, Path) for item in value):
            snapshot[name] = tuple(value)
    return snapshot


def _restore_path_globals(module, snapshot):
    for name, value in snapshot.items():
        setattr(module, name, value)


def test_legacy_config_paths_rebind_into_workspace(tmp_path):
    snapshot = _snapshot_path_globals(script_config)
    original_root = Path(script_config.PROJECT_ROOT).resolve()
    try:
        changed = _bind_legacy_config_to_workspace(tmp_path)
        assert Path(script_config.PROJECT_ROOT) == tmp_path.resolve()
        assert Path(script_config.DATA_DIR) == tmp_path.resolve() / "data"
        assert "PROJECT_ROOT" in changed
        assert Path(script_config.DATA_DIR).resolve() != original_root / "data"
    finally:
        _restore_path_globals(script_config, snapshot)


def test_source_selection_uses_explicit_immutable_classifier_root(monkeypatch, tmp_path):
    resource_root = (tmp_path / "immutable-resources").resolve()
    workspace_root = (tmp_path / "workspace").resolve()
    seen_roots = []

    def fake_classify(source, root=None):
        seen_roots.append(root)
        return "api_producer" if root == resource_root else "broken_producer"

    monkeypatch.setattr(materialization_runner, "_classify", fake_classify)
    sources = [{"source_id": "producer-only", "family": "test"}]

    selected = materialization_runner.select_sources(
        sources,
        source=None,
        family=None,
        only=None,
        classifier_root=resource_root,
    )
    wrong_root_selected = materialization_runner.select_sources(
        sources,
        source=None,
        family=None,
        only=None,
        classifier_root=workspace_root,
    )

    assert [source["source_id"] for source in selected] == ["producer-only"]
    assert wrong_root_selected == []
    assert seen_roots == [resource_root, workspace_root]


def test_materialization_dry_run_preserves_registry_denominator(monkeypatch, tmp_path):
    repo_root = Path(__file__).resolve().parents[1]
    monkeypatch.setenv("MONEYSWEEP_REGISTRY_ROOT", str(repo_root))

    result = run(root=tmp_path, dry_run=True)
    readiness = json.loads(
        (repo_root / "reports" / "materialization_readiness.json").read_text(encoding="utf-8")
    )

    assert result["dry_run"] is True
    assert result["ran"] == []
    assert result["selected_count"] == readiness["automatable_total"]
    assert Path(result["registry_root"]) == repo_root.resolve()
    assert Path(result["workspace_root"]) == tmp_path.resolve()

    latest = tmp_path / "data" / "staging" / "materialization_run_summary.json"
    receipts = list((tmp_path / "receipts" / "materialization_runs").glob("*.json"))
    assert latest.exists()
    assert len(receipts) == 1
