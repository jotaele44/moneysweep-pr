from __future__ import annotations

from copy import deepcopy

from scripts import leaderboard_release_provenance as provenance


def test_certification_runtime_manifest_is_complete_and_hash_stable():
    manifest = provenance.certification_runtime_manifest()
    assert provenance.validate_certification_runtime(manifest) == []
    assert manifest["state"] == "FROZEN"
    assert len(manifest["files"]) == len(provenance.CERTIFICATION_RUNTIME_FILES)
    first = provenance.certification_runtime_sha256(manifest)
    second = provenance.certification_runtime_sha256(deepcopy(manifest))
    assert first == second
    assert len(first) == 64


def test_certification_runtime_hash_detects_manifest_tampering():
    manifest = provenance.certification_runtime_manifest()
    original = provenance.certification_runtime_sha256(manifest)
    tampered = deepcopy(manifest)
    tampered["files"][0]["bytes"] += 1
    assert provenance.certification_runtime_sha256(tampered) != original


def test_certification_runtime_validation_fails_closed_on_missing_hash():
    manifest = provenance.certification_runtime_manifest()
    broken = deepcopy(manifest)
    broken["files"][0]["sha256"] = ""
    assert "file.sha256" in provenance.validate_certification_runtime(broken)


def test_certification_runtime_validation_fails_closed_on_missing_file_state(monkeypatch, tmp_path):
    missing = tmp_path / "missing.py"
    monkeypatch.setattr(provenance, "ROOT", tmp_path)
    monkeypatch.setattr(provenance, "CERTIFICATION_RUNTIME_FILES", [missing])
    manifest = provenance.certification_runtime_manifest()
    assert manifest["state"] == "INCOMPLETE"
    errors = provenance.validate_certification_runtime(manifest)
    assert "state" in errors
    assert "file.sha256" in errors

def test_custom_certification_runtime_binds_selected_scope_and_schema(monkeypatch, tmp_path):
    schema = tmp_path / "schema.json"
    scope = tmp_path / "scope.json"
    schema.write_text('{"schema":"asg"}', encoding="utf-8")
    scope.write_text('{"scope":"asg"}', encoding="utf-8")
    monkeypatch.setattr(provenance, "ROOT", tmp_path)
    runtime_files = [schema, scope]

    manifest = provenance.certification_runtime_manifest(runtime_files)
    assert manifest["state"] == "FROZEN"
    assert [item["path"] for item in manifest["files"]] == ["schema.json", "scope.json"]
    assert provenance.validate_certification_runtime(manifest, runtime_files) == []


def test_custom_runtime_validation_rejects_wrong_file_denominator(monkeypatch, tmp_path):
    one = tmp_path / "one.json"
    two = tmp_path / "two.json"
    one.write_text("{}", encoding="utf-8")
    two.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(provenance, "ROOT", tmp_path)
    manifest = provenance.certification_runtime_manifest([one])
    assert "files" in provenance.validate_certification_runtime(manifest, [one, two])

