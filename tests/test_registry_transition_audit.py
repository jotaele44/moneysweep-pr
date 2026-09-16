from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from tools.audit_registry_transition import (
    RegistryTransitionError, audit, canonical, compare, parse_registry, set_metrics, snapshot,
)

pytestmark = pytest.mark.unit


def run(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args], check=True,
                          capture_output=True, text=True).stdout.strip()


def commit(root: Path, text: str, extra: dict[str, str] | None = None) -> str:
    target = root / "registries/source_registry.yaml"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text)
    for name, content in (extra or {}).items():
        path = root / "registries/source_registry_extensions" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    run(root, "add", ".")
    run(root, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
        "-c", "commit.gpgsign=false", "commit", "--allow-empty", "-m", "test fixture")
    return run(root, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    run(tmp_path, "init")
    return tmp_path


BASE = 'sources:\n- source_id: alpha\n  required: true\n  validation_threshold:\n    min_rows: 1\n'


def test_exact_commits_and_raw_definitions_are_preserved(repo: Path) -> None:
    a = commit(repo, BASE)
    b = commit(repo, BASE + '- source_id: beta\n  required: false\n')
    report = audit(repo, a, b)
    assert report["source_id_sets"]["members"] == {
        "INTERSECTION": ["alpha"], "A_ONLY": [], "B_ONLY": ["beta"],
        "UNION": ["alpha", "beta"], "SYMMETRIC_DIFFERENCE": ["beta"],
    }
    assert report["required_id_sets"]["counts"]["SYMMETRIC_DIFFERENCE"] == 0
    assert report["production_eligible"] is False
    assert canonical(report) == canonical(audit(repo, a, b))
    artifact = report["A_snapshot"]["active_artifacts"][0]
    assert artifact["bytes"] == len(BASE.encode())
    assert len(artifact["sha256"]) == 64


def test_equal_counts_are_not_identity(repo: Path) -> None:
    a = commit(repo, BASE)
    b = commit(repo, BASE.replace("alpha", "beta"))
    report = audit(repo, a, b)
    assert report["source_id_sets"]["counts"]["SYMMETRIC_DIFFERENCE"] == 2
    assert report["equivalence_decision"] == "UNPROVEN"


def test_same_id_changed_contract_requires_new_binding(repo: Path) -> None:
    a = commit(repo, BASE)
    b = commit(repo, BASE.replace("min_rows: 1", "min_rows: 2"))
    report = audit(repo, a, b)
    assert report["source_id_sets"]["counts"]["SYMMETRIC_DIFFERENCE"] == 0
    assert len(report["definition_changes"]) == 1
    assert "source_definitions_changed_receipts_not_inheritable" in report["blockers"]


def test_required_changes_are_not_hidden_by_count(repo: Path) -> None:
    a = commit(repo, BASE + '- source_id: beta\n  required: false\n')
    b = commit(repo, BASE.replace('required: true', 'required: false')
               + '- source_id: beta\n  required: true\n')
    assert audit(repo, a, b)["required_id_sets"]["counts"]["SYMMETRIC_DIFFERENCE"] == 2


def test_yaml_extensions_are_inventoried_not_auto_promoted(repo: Path) -> None:
    a = commit(repo, BASE)
    b = commit(repo, BASE, {"candidate.yaml": 'sources:\n- source_id: beta\n  required: false\n'})
    report = audit(repo, a, b)
    assert report["B_snapshot"]["total_sources"] == 1
    assert report["outside_loader_changes"] == ["registries/source_registry_extensions/candidate.yaml"]


def test_json_extensions_add_records_and_duplicate_ids_fail(repo: Path) -> None:
    a = commit(repo, BASE, {"new.json": json.dumps({"sources": [{"source_id": "beta", "required": False}]})})
    assert snapshot(repo, a)["total_sources"] == 2
    b = commit(repo, BASE, {"new.json": json.dumps({"sources": [{"source_id": "alpha", "required": False}]})})
    with pytest.raises(RegistryTransitionError, match="duplicate_source_id"):
        snapshot(repo, b)


@pytest.mark.parametrize("raw,path", [
    ('sources: []\nsources: []\n', 'registry.yaml'),
    ('{"sources":[],"sources":[]}', 'registry.json'),
    ('sources:\n- source_id: alpha\n  required: true\n  required: false\n', 'registry.yaml'),
    ('{"sources":[{"source_id":"alpha","required":true,"v":1e999}]}', 'registry.json'),
    ('{"sources":[{"source_id":"alpha","required":true,"v":NaN}]}', 'registry.json'),
    ('sources:\n- source_id: " alpha "\n  required: true\n', 'registry.yaml'),
    ('sources:\n- source_id: alpha\n  required: "true"\n', 'registry.yaml'),
    ('sources:\n- source_id: alpha\n  required: true\n  date: 2026-09-13\n', 'registry.yaml'),
    ('sources:\n- &a {source_id: alpha, required: true}\n- {<<: *a}\n', 'registry.yaml'),
])
def test_malformed_ambiguous_inputs_fail_closed(raw: str, path: str) -> None:
    with pytest.raises(RegistryTransitionError):
        parse_registry(raw.encode(), path)


def test_normalized_name_is_not_source_identity(repo: Path) -> None:
    a = commit(repo, BASE.replace('alpha', 'Álpha'))
    b = commit(repo, BASE.replace('alpha', 'Alpha'))
    assert audit(repo, a, b)["source_id_sets"]["counts"]["SYMMETRIC_DIFFERENCE"] == 2


def test_symlink_registry_rejected(repo: Path) -> None:
    a = commit(repo, BASE)
    path = repo / 'registries/source_registry.yaml'
    path.unlink()
    path.symlink_to('../untrusted.yaml')
    run(repo, 'add', '.')
    run(repo, '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
        '-c', 'commit.gpgsign=false', 'commit', '-m', 'symlink')
    with pytest.raises(RegistryTransitionError, match='nonregular_registry_entry'):
        snapshot(repo, run(repo, 'rev-parse', 'HEAD'))
    assert snapshot(repo, a)['total_sources'] == 1


def test_mutable_refs_rejected(repo: Path) -> None:
    commit(repo, BASE)
    with pytest.raises(RegistryTransitionError, match='exact_lowercase_commit_sha_required'):
        snapshot(repo, 'HEAD')


def test_empty_set_arithmetic() -> None:
    assert set_metrics(set(), set())['counts'] == {k: 0 for k in (
        'INTERSECTION', 'A_ONLY', 'B_ONLY', 'UNION', 'SYMMETRIC_DIFFERENCE')}


def test_loader_profiles_must_match(repo: Path) -> None:
    a = snapshot(repo, commit(repo, BASE))
    b = dict(a)
    b['loader_profile'] = 'different'
    with pytest.raises(RegistryTransitionError, match='loader_profiles_noncomparable'):
        compare(a, b)


def test_cli_refuses_overwriting_existing_output(repo: Path, tmp_path: Path) -> None:
    import sys
    a = commit(repo, BASE)
    out = tmp_path / 'retained.json'
    out.write_text('preserve me')
    script = Path(__file__).resolve().parents[1] / 'tools/audit_registry_transition.py'
    result = subprocess.run([sys.executable, str(script), '--root', str(repo), '--a-sha', a,
                             '--b-sha', a, '--output', str(out)], capture_output=True)
    assert result.returncode == 2
    assert out.read_text() == 'preserve me'


def test_runtime_override_divergence_is_not_count_equivalence(repo: Path) -> None:
    import yaml
    a = commit(repo, BASE)
    (repo / "registries/source_registry.json").write_text(json.dumps(yaml.safe_load(BASE)))
    folder = repo / "registries/source_registry_overrides"
    folder.mkdir()
    (folder / "change.json").write_text(json.dumps({"source_overrides": [
        {"source_id": "alpha", "producer_script": "scripts/different.py"}]}))
    b = commit(repo, BASE)
    report = audit(repo, a, b)
    assert report["cross_profile_comparison"]["B"]["source_id_sets"]["counts"]["SYMMETRIC_DIFFERENCE"] == 0
    assert report["cross_profile_comparison"]["B"]["changed_definition_ids"] == ["alpha"]
    assert "runtime_certification_profile_divergence:B" in report["blockers"]


def test_matching_runtime_profile_and_definition_is_positive(repo: Path) -> None:
    import yaml
    commit(repo, BASE)
    (repo / "registries/source_registry.json").write_text(json.dumps(yaml.safe_load(BASE)))
    a = commit(repo, BASE)
    report = audit(repo, a, a)
    assert report["blockers"] == []
    assert report["equivalence_decision"] == "IDENTICAL_ACTIVE_DEFINITIONS"
    assert report["state"] == "AUDIT_ONLY"
    assert report["production_eligible"] is False


@pytest.mark.parametrize("override", [
    {"source_id": "missing", "producer_script": "x"},
    {"source_id": "alpha", "required": False},
    {"source_id": "alpha", "required": 1},
    {"source_id": " alpha ", "producer_script": "x"},
])
def test_runtime_invalid_overrides_fail_closed(repo: Path, override: dict) -> None:
    import yaml
    commit(repo, BASE)
    (repo / "registries/source_registry.json").write_text(json.dumps(yaml.safe_load(BASE)))
    folder = repo / "registries/source_registry_overrides"
    folder.mkdir()
    (folder / "bad.json").write_text(json.dumps({"source_overrides": [override]}))
    b = commit(repo, BASE)
    with pytest.raises(RegistryTransitionError):
        snapshot(repo, b)
